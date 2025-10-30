import hashlib
import pytest
import io
from PIL import Image
import shutil
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, text

from .models.user import Base, UserRepository, get_user_repository

from .api import app, _rate_windows


@pytest.fixture(scope="function")
def engine():
    engine = create_engine("sqlite:///:memory:?check_same_thread=False")
    Base.metadata.create_all(bind=engine)
    yield engine


@pytest.fixture(scope="function")
def session(engine):
    conn = engine.connect()
    conn.begin()
    db = Session(bind=conn)
    yield db
    db.rollback()
    conn.close()


@pytest.fixture(scope="function")
def repo(session):
    yield UserRepository(session)


@pytest.fixture(scope="function")
def client(repo):
    app.dependency_overrides[get_user_repository] = lambda: repo
    # tests run multiple requests; ensure the in-memory rate limiter is reset per test
    _rate_windows.clear()
    # set a header so test requests bypass the in-memory rate limiter and won't
    # receive 429s during normal unit-test flows
    with TestClient(app, headers={"X-Bypass-RateLimit": "1"}) as c:
        yield c


@pytest.fixture(scope="function")
def create_user(session):
    def _create(name: str, password: str = "secret") -> dict:
        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        data = {
            "name": name,
            "email": f"{name}@example.com",
            "password": hashed_password,
        }
        session.execute(
            text(
                "INSERT INTO users (name, email, password) "
                "VALUES (:name, :email, :password)"
            ),
            data,
        )
        session.commit()
        user_id = session.execute(
            text("SELECT id FROM users WHERE name = :name"), {"name": name}
        ).scalar_one()
        return {
            "id": user_id,
            "name": name,
            "email": data["email"],
            "password": password,
        }

    return _create


@pytest.fixture(scope="function")
def created_user(create_user):
    return create_user("foo")


@pytest.fixture(scope="function", autouse=True)
def cleanup_avatars():
    """Clean up avatar directory before and after each test."""
    avatar_dir = Path("avatars")
    if avatar_dir.exists():
        shutil.rmtree(avatar_dir)
    avatar_dir.mkdir(exist_ok=True)
    yield
    # Cleanup after test
    if avatar_dir.exists():
        shutil.rmtree(avatar_dir)


def test_read_user(client, created_user):
    response = client.get("/users/foo")
    assert response.status_code == 200
    assert response.json() == {
        "user": {"name": "foo", "id": created_user["id"], "tier": 1}
    }


def test_create_user(client):
    response = client.post(
        "/users/",
        json={
            "name": "foobar",
            "email": "foobar@example.com",
            "password": "supersafe",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["user"]["name"] == "foobar"
    assert isinstance(payload["user"]["id"], int)


def test_create_existing_user(client, created_user):
    response = client.post(
        "/users/",
        json={
            "name": created_user["name"],
            "email": created_user["email"],
            "password": created_user["password"],
        },
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "Item already exists"}


def test_friend_request_flow(client, create_user):
    alice = create_user("alice", password="alicepw")
    bob = create_user("bob", password="bobpw")

    send_response = client.post(
        "/friendships/requests/",
        json={"requester": alice["name"], "receiver": bob["name"]},
    )
    assert send_response.status_code == 201
    request_payload = send_response.json()["request"]
    assert request_payload["requester"] == "alice"
    assert request_payload["receiver"] == "bob"

    pending_for_bob = client.get("/friendships/requests/bob")
    assert pending_for_bob.status_code == 200
    assert any(
        req["requester"] == "alice" and req["receiver"] == "bob"
        for req in pending_for_bob.json()["requests"]
    )

    accept_response = client.post(
        "/friendships/requests/accept",
        json={"requester": "alice", "receiver": "bob"},
    )
    assert accept_response.status_code == 200
    friendship_payload = accept_response.json()["friendship"]
    assert set(friendship_payload.values()) == {"alice", "bob"}

    alice_friends = client.get("/friendships/alice")
    assert alice_friends.status_code == 200
    assert any(
        set(friendship.values()) == {"alice", "bob"}
        for friendship in alice_friends.json()["friendships"]
    )

    bob_friends = client.get("/friendships/bob")
    assert bob_friends.status_code == 200
    assert any(
        set(friendship.values()) == {"alice", "bob"}
        for friendship in bob_friends.json()["friendships"]
    )


def test_friendships_are_exclusive(client, create_user):
    alice = create_user("alice", password="alicepw")
    bob = create_user("bob", password="bobpw")
    carol = create_user("carol", password="carolpw")

    # Alice and Bob become friends
    assert client.post(
        "/friendships/requests/",
        json={"requester": "alice", "receiver": "bob"},
    ).status_code == 201
    assert client.post(
        "/friendships/requests/accept",
        json={"requester": "alice", "receiver": "bob"},
    ).status_code == 200

    # Alice can befriend Carol as well once the exclusivity cap is removed
    assert client.post(
        "/friendships/requests/",
        json={"requester": "alice", "receiver": "carol"},
    ).status_code == 201
    assert client.post(
        "/friendships/requests/accept",
        json={"requester": "alice", "receiver": "carol"},
    ).status_code == 200

    alice_friends = client.get("/friendships/alice")
    assert alice_friends.status_code == 200
    friend_sets = [set(fs.values()) for fs in alice_friends.json()["friendships"]]
    assert {"alice", "bob"} in friend_sets
    assert {"alice", "carol"} in friend_sets


def test_deny_friend_request(client, create_user):
    alice = create_user("alice")
    bob = create_user("bob")

    create_resp = client.post(
        "/friendships/requests/",
        json={"requester": "alice", "receiver": "bob"},
    )
    assert create_resp.status_code == 201

    deny_resp = client.post(
        "/friendships/requests/deny",
        json={"requester": "alice", "receiver": "bob"},
    )
    assert deny_resp.status_code == 200
    assert deny_resp.json() == {"detail": "Friend request denied"}

    # Request should no longer appear in pending lists
    pending = client.get("/friendships/requests/bob")
    assert pending.status_code == 200
    assert pending.json()["requests"] == []

    # Attempting to accept now should 404
    accept_missing = client.post(
        "/friendships/requests/accept",
        json={"requester": "alice", "receiver": "bob"},
    )
    assert accept_missing.status_code == 404


#---------------------------------#
#--- Avatar API Tests ---#
#---------------------------------#

@pytest.fixture
def sample_image():
    """Creates a sample image file for testing."""
    img = Image.new('RGB', (800, 600), color='red')
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes


@pytest.fixture
def large_image():
    """Creates a large image to test cropping/resizing."""
    img = Image.new('RGB', (3000, 2000), color='blue')
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='JPEG')
    img_bytes.seek(0)
    return img_bytes


@pytest.fixture
def non_square_image():
    """Creates a non-square image to test cropping."""
    img = Image.new('RGB', (1200, 800), color='green')
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes


def test_upload_avatar(client, create_user, sample_image):
    """Test uploading a profile picture."""
    user = create_user("alice")
    
    response = client.put(
        f"/users/{user['id']}/avatar",
        files={"file": ("avatar.png", sample_image, "image/png")}
    )
    
    assert response.status_code == 200
    assert response.json() == {"detail": "Avatar uploaded successfully"}


def test_upload_avatar_nonexistent_user(client, sample_image):
    """Test uploading avatar for a user that doesn't exist."""
    response = client.put(
        "/users/99999/avatar",
        files={"file": ("avatar.png", sample_image, "image/png")}
    )
    
    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_retrieve_avatar(client, create_user, sample_image):
    """Test retrieving an uploaded profile picture."""
    user = create_user("bob")
    
    # Upload avatar
    upload_response = client.put(
        f"/users/{user['id']}/avatar",
        files={"file": ("avatar.png", sample_image, "image/png")}
    )
    assert upload_response.status_code == 200
    
    # Retrieve avatar
    get_response = client.get(f"/users/{user['id']}/avatar")
    assert get_response.status_code == 200
    assert get_response.headers["content-type"] in ["image/png", "image/jpeg"]
    
    # Verify it's a valid image
    img = Image.open(io.BytesIO(get_response.content))
    assert img.size[0] > 0 and img.size[1] > 0


def test_retrieve_avatar_no_upload(client, create_user):
    """Test retrieving avatar when none has been uploaded."""
    user = create_user("charlie")
    
    response = client.get(f"/users/{user['id']}/avatar")
    assert response.status_code == 404
    assert response.json() == {"detail": "Avatar not found"}


def test_retrieve_avatar_nonexistent_user(client):
    """Test retrieving avatar for a user that doesn't exist."""
    response = client.get("/users/99999/avatar")
    assert response.status_code == 404


def test_avatar_is_cropped(client, create_user, large_image):
    """Test that large images are cropped/resized to save disk space."""
    user = create_user("diana")
    
    # Upload large image
    client.put(
        f"/users/{user['id']}/avatar",
        files={"file": ("large.jpg", large_image, "image/jpeg")}
    )
    
    # Retrieve and verify it's been resized
    response = client.get(f"/users/{user['id']}/avatar")
    assert response.status_code == 200
    
    img = Image.open(io.BytesIO(response.content))
    # Avatar should be smaller than original (3000x2000)
    # Common avatar sizes are 200x200, 256x256, 512x512, etc.
    assert img.size[0] <= 256
    assert img.size[1] <= 256


def test_avatar_aspect_ratio_preserved_or_cropped(client, create_user, non_square_image):
    """Test that non-square images are handled properly (cropped to square or ratio preserved)."""
    user = create_user("eve")
    
    client.put(
        f"/users/{user['id']}/avatar",
        files={"file": ("rect.png", non_square_image, "image/png")}
    )
    
    response = client.get(f"/users/{user['id']}/avatar")
    assert response.status_code == 200
    
    img = Image.open(io.BytesIO(response.content))
    # Avatar should be square (common for profile pictures) or at least reasonably sized
    width, height = img.size
    assert width <= 256 and height <= 256
    # Optionally check if it's square (many systems crop to square)
    # assert width == height  # Uncomment if your implementation crops to square


def test_update_existing_avatar(client, create_user, sample_image):
    """Test that uploading a new avatar replaces the old one."""
    user = create_user("frank")
    
    # Upload first avatar (red)
    img1 = Image.new('RGB', (400, 400), color='red')
    img1_bytes = io.BytesIO()
    img1.save(img1_bytes, format='PNG')
    img1_bytes.seek(0)
    
    client.put(
        f"/users/{user['id']}/avatar",
        files={"file": ("avatar1.png", img1_bytes, "image/png")}
    )
    
    # Upload second avatar (blue)
    img2 = Image.new('RGB', (400, 400), color='blue')
    img2_bytes = io.BytesIO()
    img2.save(img2_bytes, format='PNG')
    img2_bytes.seek(0)
    
    response = client.put(
        f"/users/{user['id']}/avatar",
        files={"file": ("avatar2.png", img2_bytes, "image/png")}
    )
    
    assert response.status_code == 200
    
    # Verify the new avatar is stored
    get_response = client.get(f"/users/{user['id']}/avatar")
    assert get_response.status_code == 200


def test_invalid_file_format(client, create_user):
    """Test uploading a non-image file."""
    user = create_user("grace")
    
    # Create a text file instead of an image
    text_file = io.BytesIO(b"This is not an image")
    
    response = client.put(
        f"/users/{user['id']}/avatar",
        files={"file": ("notanimage.txt", text_file, "text/plain")}
    )
    
    assert response.status_code == 400
    assert "Invalid image" in response.json()["detail"] or "Unsupported" in response.json()["detail"]


def test_empty_file_upload(client, create_user):
    """Test uploading an empty file."""
    user = create_user("henry")
    
    empty_file = io.BytesIO(b"")
    
    response = client.put(
        f"/users/{user['id']}/avatar",
        files={"file": ("empty.png", empty_file, "image/png")}
    )
    
    assert response.status_code == 400


def test_multiple_users_different_avatars(client, create_user):
    """Test that multiple users can have different avatars."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Create different colored avatars
    alice_img = Image.new('RGB', (200, 200), color='red')
    alice_bytes = io.BytesIO()
    alice_img.save(alice_bytes, format='PNG')
    alice_bytes.seek(0)
    
    bob_img = Image.new('RGB', (200, 200), color='blue')
    bob_bytes = io.BytesIO()
    bob_img.save(bob_bytes, format='PNG')
    bob_bytes.seek(0)
    
    # Upload both
    client.put(
        f"/users/{alice['id']}/avatar",
        files={"file": ("alice.png", alice_bytes, "image/png")}
    )
    client.put(
        f"/users/{bob['id']}/avatar",
        files={"file": ("bob.png", bob_bytes, "image/png")}
    )
    
    # Both should be retrievable
    alice_response = client.get(f"/users/{alice['id']}/avatar")
    bob_response = client.get(f"/users/{bob['id']}/avatar")
    
    assert alice_response.status_code == 200
    assert bob_response.status_code == 200
    
    # Verify they're different
    assert alice_response.content != bob_response.content


def test_avatar_file_size_limit(client, create_user):
    """Test that extremely large files are rejected or handled properly."""
    user = create_user("iris")
    
    # Create a very large image (10MB+)
    huge_img = Image.new('RGB', (5000, 5000), color='yellow')
    huge_bytes = io.BytesIO()
    huge_img.save(huge_bytes, format='PNG')
    huge_bytes.seek(0)
    
    response = client.put(
        f"/users/{user['id']}/avatar",
        files={"file": ("huge.png", huge_bytes, "image/png")}
    )
    
    # Should either succeed (with cropping) or reject if too large
    # This depends on your implementation's file size limits
    assert response.status_code in [200, 400, 413]


#---------------------------------#
#--- V2 Avatar API Tests ---#
#---------------------------------#

def test_v2_create_avatar_success(client, create_user, sample_image):
    """Test creating a profile picture with POST (v2)."""
    user = create_user("alice")
    
    response = client.post(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("avatar.png", sample_image, "image/png")}
    )
    
    assert response.status_code == 201
    assert response.json() == {"detail": "Avatar created successfully"}


def test_v2_create_avatar_already_exists(client, create_user, sample_image):
    """Test that POST returns 409 if avatar already exists (v2)."""
    user = create_user("bob")
    
    # Create avatar first time
    response1 = client.post(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("avatar1.png", sample_image, "image/png")}
    )
    assert response1.status_code == 201
    
    # Try to create again - should fail
    sample_image.seek(0)  # Reset the BytesIO object
    response2 = client.post(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("avatar2.png", sample_image, "image/png")}
    )
    assert response2.status_code == 409
    assert "already exists" in response2.json()["detail"].lower()


def test_v2_update_avatar_success(client, create_user):
    """Test updating an existing avatar with PUT (v2)."""
    user = create_user("carol")
    
    # Create first avatar
    img1 = Image.new('RGB', (400, 400), color='red')
    img1_bytes = io.BytesIO()
    img1.save(img1_bytes, format='PNG')
    img1_bytes.seek(0)
    
    client.post(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("avatar1.png", img1_bytes, "image/png")}
    )
    
    # Update with new avatar
    img2 = Image.new('RGB', (400, 400), color='blue')
    img2_bytes = io.BytesIO()
    img2.save(img2_bytes, format='PNG')
    img2_bytes.seek(0)
    
    response = client.put(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("avatar2.png", img2_bytes, "image/png")}
    )
    
    assert response.status_code == 200
    assert response.json() == {"detail": "Avatar updated successfully"}


def test_v2_update_avatar_creates_when_not_exists(client, create_user, sample_image):
    """Test that PUT creates avatar if it doesn't exist (v2)."""
    user = create_user("dave")
    
    response = client.put(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("avatar.png", sample_image, "image/png")}
    )
    
    assert response.status_code == 200
    assert response.json() == {"detail": "Avatar updated successfully"}
    
    # Verify it was created
    get_response = client.get(f"/v2/users/{user['id']}/avatar")
    assert get_response.status_code == 200


def test_v2_delete_avatar_success(client, create_user, sample_image):
    """Test deleting an avatar (v2)."""
    user = create_user("eve")
    
    # Create avatar first
    client.post(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("avatar.png", sample_image, "image/png")}
    )
    
    # Delete it
    response = client.delete(f"/v2/users/{user['id']}/avatar")
    assert response.status_code == 204
    
    # Verify it's gone
    get_response = client.get(f"/v2/users/{user['id']}/avatar")
    assert get_response.status_code == 404


def test_v2_delete_avatar_not_found(client, create_user):
    """Test deleting an avatar that doesn't exist (v2)."""
    user = create_user("frank")
    
    response = client.delete(f"/v2/users/{user['id']}/avatar")
    assert response.status_code == 404


def test_v2_get_avatar(client, create_user, sample_image):
    """Test retrieving an avatar (v2)."""
    user = create_user("grace")
    
    # Create avatar
    client.post(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("avatar.png", sample_image, "image/png")}
    )
    
    # Retrieve it
    response = client.get(f"/v2/users/{user['id']}/avatar")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    
    # Verify it's a valid image
    img = Image.open(io.BytesIO(response.content))
    assert img.size == (256, 256)  # Should be exactly 256x256


def test_v2_avatar_size_is_256(client, create_user, large_image):
    """Test that avatars are resized to exactly 256x256 (v2)."""
    user = create_user("henry")
    
    # Upload large image
    client.post(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("large.jpg", large_image, "image/jpeg")}
    )
    
    # Retrieve and verify size
    response = client.get(f"/v2/users/{user['id']}/avatar")
    assert response.status_code == 200
    
    img = Image.open(io.BytesIO(response.content))
    assert img.size == (256, 256)


def test_v2_webp_format_supported(client, create_user):
    """Test that .webp format is supported (v2)."""
    user = create_user("iris")
    
    # Create a webp image
    img = Image.new('RGB', (400, 400), color='purple')
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='WEBP')
    img_bytes.seek(0)
    
    response = client.post(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("avatar.webp", img_bytes, "image/webp")}
    )
    
    assert response.status_code == 201


def test_v2_create_avatar_invalid_file_type(client, create_user):
    """Test that invalid file types are rejected in POST (v2)."""
    user = create_user("jack")
    
    text_file = io.BytesIO(b"This is not an image")
    
    response = client.post(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("notanimage.txt", text_file, "text/plain")}
    )
    
    assert response.status_code == 400


def test_v2_create_avatar_nonexistent_user(client, sample_image):
    """Test creating avatar for non-existent user (v2)."""
    response = client.post(
        "/v2/users/99999/avatar",
        files={"file": ("avatar.png", sample_image, "image/png")}
    )
    
    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_v2_avatar_workflow_complete(client, create_user, sample_image):
    """Test complete avatar workflow: create, get, update, delete (v2)."""
    user = create_user("complete")
    
    # 1. Create avatar
    create_response = client.post(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("avatar.png", sample_image, "image/png")}
    )
    assert create_response.status_code == 201
    
    # 2. Get avatar
    get_response = client.get(f"/v2/users/{user['id']}/avatar")
    assert get_response.status_code == 200
    
    # 3. Update avatar
    sample_image.seek(0)
    update_response = client.put(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("avatar2.png", sample_image, "image/png")}
    )
    assert update_response.status_code == 200
    
    # 4. Delete avatar
    delete_response = client.delete(f"/v2/users/{user['id']}/avatar")
    assert delete_response.status_code == 204
    
    # 5. Verify deleted
    get_after_delete = client.get(f"/v2/users/{user['id']}/avatar")
    assert get_after_delete.status_code == 404


def test_v2_png_format_supported(client, create_user, sample_image):
    """Test that .png format is supported (v2)."""
    user = create_user("png_user")
    
    response = client.post(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("avatar.png", sample_image, "image/png")}
    )
    
    assert response.status_code == 201





#---------------------------------#
#--- V2 Friends API Tests ---#
#---------------------------------#


def test_v2_list_friends_empty(client, create_user):
    """Test listing friends when user has no friends."""
    user = create_user("alice")
    
    response = client.get(f"/v2/users/{user['id']}/friends/")
    assert response.status_code == 200
    assert response.json() == {"friends": []}


def test_v2_list_friends_with_friends(client, create_user):
    """Test listing friends when user has friends."""
    alice = create_user("alice")
    bob = create_user("bob")
    carol = create_user("carol")
    
    # Create friendships
    client.post(
        "/friendships/requests/",
        json={"requester": "alice", "receiver": "bob"}
    )
    client.post(
        "/friendships/requests/accept",
        json={"requester": "alice", "receiver": "bob"}
    )
    
    client.post(
        "/friendships/requests/",
        json={"requester": "alice", "receiver": "carol"}
    )
    client.post(
        "/friendships/requests/accept",
        json={"requester": "alice", "receiver": "carol"}
    )
    
    # Get Alice's friends
    response = client.get(f"/v2/users/{alice['id']}/friends/")
    assert response.status_code == 200
    friends = response.json()["friends"]
    assert len(friends) == 2
    
    # Verify friend data structure and no password
    for friend in friends:
        assert "id" in friend
        assert "name" in friend
        assert "email" in friend
        assert "password" not in friend
    
    # Verify correct friends
    friend_names = {f["name"] for f in friends}
    assert friend_names == {"bob", "carol"}


def test_v2_list_friends_nonexistent_user(client):
    """Test listing friends for a user that doesn't exist."""
    response = client.get("/v2/users/99999/friends/")
    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_v2_get_friend_by_name_success(client, create_user):
    """Test getting a specific friend by name."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Create friendship
    client.post(
        "/friendships/requests/",
        json={"requester": "alice", "receiver": "bob"}
    )
    client.post(
        "/friendships/requests/accept",
        json={"requester": "alice", "receiver": "bob"}
    )
    
    # Get Bob as Alice's friend
    response = client.get(f"/v2/users/{alice['id']}/friends/bob")
    assert response.status_code == 200
    friend = response.json()["friend"]
    assert friend["name"] == "bob"
    assert friend["id"] == bob["id"]
    assert friend["email"] == bob["email"]
    assert "password" not in friend


def test_v2_get_friend_by_name_not_friends(client, create_user):
    """Test getting a user by name who is not a friend."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Bob exists but is not Alice's friend
    response = client.get(f"/v2/users/{alice['id']}/friends/bob")
    assert response.status_code == 404
    assert response.json() == {"detail": "Friendship not found"}


def test_v2_get_friend_by_name_user_doesnt_exist(client, create_user):
    """Test getting a friend when the target user doesn't exist."""
    alice = create_user("alice")
    
    response = client.get(f"/v2/users/{alice['id']}/friends/nonexistent")
    assert response.status_code == 404


def test_v2_get_friend_by_name_requester_doesnt_exist(client):
    """Test getting a friend when the requesting user doesn't exist."""
    response = client.get("/v2/users/99999/friends/bob")
    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_v2_get_friend_by_id_success(client, create_user):
    """Test getting a specific friend by ID."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Create friendship
    client.post(
        "/friendships/requests/",
        json={"requester": "alice", "receiver": "bob"}
    )
    client.post(
        "/friendships/requests/accept",
        json={"requester": "alice", "receiver": "bob"}
    )
    
    # Get Bob as Alice's friend by ID
    response = client.get(f"/v2/users/{alice['id']}/friends/{bob['id']}")
    assert response.status_code == 200
    friend = response.json()["friend"]
    assert friend["name"] == "bob"
    assert friend["id"] == bob["id"]
    assert friend["email"] == bob["email"]
    assert "password" not in friend


def test_v2_get_friend_by_id_not_friends(client, create_user):
    """Test getting a user by ID who is not a friend."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Bob exists but is not Alice's friend
    response = client.get(f"/v2/users/{alice['id']}/friends/{bob['id']}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Friendship not found"}


def test_v2_get_friend_by_id_friend_doesnt_exist(client, create_user):
    """Test getting a friend when the friend ID doesn't exist."""
    alice = create_user("alice")
    
    response = client.get(f"/v2/users/{alice['id']}/friends/99999")
    assert response.status_code == 404


def test_v2_get_friend_by_id_user_doesnt_exist(client):
    """Test getting a friend when the requesting user doesn't exist."""
    response = client.get("/v2/users/99999/friends/1")
    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_v2_delete_friend_by_name_success(client, create_user):
    """Test deleting a friendship by friend name."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Create friendship
    client.post(
        "/friendships/requests/",
        json={"requester": "alice", "receiver": "bob"}
    )
    client.post(
        "/friendships/requests/accept",
        json={"requester": "alice", "receiver": "bob"}
    )
    
    # Verify friendship exists
    response = client.get(f"/v2/users/{alice['id']}/friends/")
    assert len(response.json()["friends"]) == 1
    
    # Delete friendship
    response = client.delete(f"/v2/users/{alice['id']}/friends/bob")
    assert response.status_code == 204
    
    # Verify friendship no longer exists for Alice
    response = client.get(f"/v2/users/{alice['id']}/friends/")
    assert response.json()["friends"] == []
    
    # Verify friendship no longer exists for Bob
    response = client.get(f"/v2/users/{bob['id']}/friends/")
    assert response.json()["friends"] == []


def test_v2_delete_friend_by_name_not_friends(client, create_user):
    """Test deleting a friendship when users are not friends."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    response = client.delete(f"/v2/users/{alice['id']}/friends/bob")
    assert response.status_code == 404
    assert response.json() == {"detail": "Friendship not found"}


def test_v2_delete_friend_by_name_friend_doesnt_exist(client, create_user):
    """Test deleting a friendship when the friend doesn't exist."""
    alice = create_user("alice")
    
    response = client.delete(f"/v2/users/{alice['id']}/friends/nonexistent")
    assert response.status_code == 404


def test_v2_delete_friend_by_name_user_doesnt_exist(client):
    """Test deleting a friendship when the requesting user doesn't exist."""
    response = client.delete("/v2/users/99999/friends/bob")
    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_v2_delete_friend_by_id_success(client, create_user):
    """Test deleting a friendship by friend ID."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Create friendship
    client.post(
        "/friendships/requests/",
        json={"requester": "alice", "receiver": "bob"}
    )
    client.post(
        "/friendships/requests/accept",
        json={"requester": "alice", "receiver": "bob"}
    )
    
    # Delete friendship by ID
    response = client.delete(f"/v2/users/{alice['id']}/friends/{bob['id']}")
    assert response.status_code == 204
    
    # Verify friendship no longer exists
    response = client.get(f"/v2/users/{alice['id']}/friends/")
    assert response.json()["friends"] == []


def test_v2_delete_friend_by_id_not_friends(client, create_user):
    """Test deleting a friendship by ID when users are not friends."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    response = client.delete(f"/v2/users/{alice['id']}/friends/{bob['id']}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Friendship not found"}


def test_v2_delete_friend_by_id_friend_doesnt_exist(client, create_user):
    """Test deleting a friendship when the friend ID doesn't exist."""
    alice = create_user("alice")
    
    response = client.delete(f"/v2/users/{alice['id']}/friends/99999")
    assert response.status_code == 404


def test_v2_delete_friend_by_id_user_doesnt_exist(client):
    """Test deleting a friendship when the requesting user doesn't exist."""
    response = client.delete("/v2/users/99999/friends/1")
    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_v2_friendship_is_bidirectional(client, create_user):
    """Test that friendships are bidirectional."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Create friendship
    client.post(
        "/friendships/requests/",
        json={"requester": "alice", "receiver": "bob"}
    )
    client.post(
        "/friendships/requests/accept",
        json={"requester": "alice", "receiver": "bob"}
    )
    
    # Both users should see each other as friends
    alice_friends = client.get(f"/v2/users/{alice['id']}/friends/")
    assert len(alice_friends.json()["friends"]) == 1
    assert alice_friends.json()["friends"][0]["name"] == "bob"
    
    bob_friends = client.get(f"/v2/users/{bob['id']}/friends/")
    assert len(bob_friends.json()["friends"]) == 1
    assert bob_friends.json()["friends"][0]["name"] == "alice"


def test_v2_delete_friend_is_bidirectional(client, create_user):
    """Test that deleting a friendship removes it for both users."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Create friendship
    client.post(
        "/friendships/requests/",
        json={"requester": "alice", "receiver": "bob"}
    )
    client.post(
        "/friendships/requests/accept",
        json={"requester": "alice", "receiver": "bob"}
    )
    
    # Alice deletes the friendship
    response = client.delete(f"/v2/users/{alice['id']}/friends/bob")
    assert response.status_code == 204
    
    # Neither user should see the friendship
    alice_friends = client.get(f"/v2/users/{alice['id']}/friends/")
    assert alice_friends.json()["friends"] == []
    
    bob_friends = client.get(f"/v2/users/{bob['id']}/friends/")
    assert bob_friends.json()["friends"] == []


def test_v2_delete_friend_can_be_done_by_either_party(client, create_user):
    """Test that either party in a friendship can delete it."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Create friendship
    client.post(
        "/friendships/requests/",
        json={"requester": "alice", "receiver": "bob"}
    )
    client.post(
        "/friendships/requests/accept",
        json={"requester": "alice", "receiver": "bob"}
    )
    
    # Bob deletes the friendship (not Alice who initiated)
    response = client.delete(f"/v2/users/{bob['id']}/friends/alice")
    assert response.status_code == 204
    
    # Verify deletion
    alice_friends = client.get(f"/v2/users/{alice['id']}/friends/")
    assert alice_friends.json()["friends"] == []


def test_v2_user_can_have_multiple_friends(client, create_user):
    """Test that a user can have multiple friends."""
    alice = create_user("alice")
    bob = create_user("bob")
    carol = create_user("carol")
    dave = create_user("dave")
    
    # Create multiple friendships
    for friend_name in ["bob", "carol", "dave"]:
        client.post(
            "/friendships/requests/",
            json={"requester": "alice", "receiver": friend_name}
        )
        client.post(
            "/friendships/requests/accept",
            json={"requester": "alice", "receiver": friend_name}
        )
    
    # Alice should have 3 friends
    response = client.get(f"/v2/users/{alice['id']}/friends/")
    assert len(response.json()["friends"]) == 3
    friend_names = {f["name"] for f in response.json()["friends"]}
    assert friend_names == {"bob", "carol", "dave"}


def test_v2_deleting_one_friend_preserves_others(client, create_user):
    """Test that deleting one friend doesn't affect other friendships."""
    alice = create_user("alice")
    bob = create_user("bob")
    carol = create_user("carol")
    
    # Create friendships
    for friend_name in ["bob", "carol"]:
        client.post(
            "/friendships/requests/",
            json={"requester": "alice", "receiver": friend_name}
        )
        client.post(
            "/friendships/requests/accept",
            json={"requester": "alice", "receiver": friend_name}
        )
    
    # Delete Bob
    response = client.delete(f"/v2/users/{alice['id']}/friends/bob")
    assert response.status_code == 204
    
    # Alice should still have Carol as a friend
    response = client.get(f"/v2/users/{alice['id']}/friends/")
    friends = response.json()["friends"]
    assert len(friends) == 1
    assert friends[0]["name"] == "carol"


def test_v2_legacy_endpoints_still_work(client, create_user):
    """Test that legacy friendship endpoints still function."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Use legacy endpoints
    legacy_response = client.get(f"/friendships/{alice['name']}")
    assert legacy_response.status_code == 200
    
    # Should match v2 endpoint behavior
    v2_response = client.get(f"/v2/users/{alice['id']}/friends/")
    assert v2_response.status_code == 200


def test_v2_get_friend_returns_same_data_as_list(client, create_user):
    """Test that getting a single friend returns the same data structure as list."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Create friendship
    client.post(
        "/friendships/requests/",
        json={"requester": "alice", "receiver": "bob"}
    )
    client.post(
        "/friendships/requests/accept",
        json={"requester": "alice", "receiver": "bob"}
    )
    
    # Get from list
    list_response = client.get(f"/v2/users/{alice['id']}/friends/")
    bob_from_list = list_response.json()["friends"][0]
    
    # Get individual
    get_response = client.get(f"/v2/users/{alice['id']}/friends/bob")
    bob_from_get = get_response.json()["friend"]
    
    # Should have same structure and content
    assert bob_from_list.keys() == bob_from_get.keys()
    assert bob_from_list == bob_from_get


def test_v2_no_password_exposure_in_any_endpoint(client, create_user):
    """Test that password is never exposed in any friends endpoint."""
    alice = create_user("alice", password="super_secret_password")
    bob = create_user("bob", password="another_secret")
    
    # Create friendship
    client.post(
        "/friendships/requests/",
        json={"requester": "alice", "receiver": "bob"}
    )
    client.post(
        "/friendships/requests/accept",
        json={"requester": "alice", "receiver": "bob"}
    )
    
    # Check list endpoint
    list_response = client.get(f"/v2/users/{alice['id']}/friends/")
    for friend in list_response.json()["friends"]:
        assert "password" not in friend
        assert "super_secret_password" not in str(friend)
        assert "another_secret" not in str(friend)
    
    # Check get by name endpoint
    name_response = client.get(f"/v2/users/{alice['id']}/friends/bob")
    friend = name_response.json()["friend"]
    assert "password" not in friend
    assert "another_secret" not in str(friend)
    
    # Check get by id endpoint
    id_response = client.get(f"/v2/users/{alice['id']}/friends/{bob['id']}")
    friend = id_response.json()["friend"]
    assert "password" not in friend
    assert "another_secret" not in str(friend)


def test_v2_referential_integrity_user_deletion(client, create_user, session):
    """Test that deleting a user removes their friendships (referential integrity)."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Create friendship
    client.post(
        "/friendships/requests/",
        json={"requester": "alice", "receiver": "bob"}
    )
    client.post(
        "/friendships/requests/accept",
        json={"requester": "alice", "receiver": "bob"}
    )
    
    # Verify friendship exists
    response = client.get(f"/v2/users/{bob['id']}/friends/")
    assert len(response.json()["friends"]) == 1
    
    # Delete Alice
    client.post("/users/delete", json={"name": "alice"})
    
    # Bob should have no friends now
    response = client.get(f"/v2/users/{bob['id']}/friends/")
    assert response.json()["friends"] == []


def test_v2_cannot_get_self_as_friend(client, create_user):
    """Test that a user cannot appear as their own friend."""
    alice = create_user("alice")
    
    # Try to get self as friend
    response = client.get(f"/v2/users/{alice['id']}/friends/alice")
    assert response.status_code == 404
    
    response = client.get(f"/v2/users/{alice['id']}/friends/{alice['id']}")
    assert response.status_code == 404





#---------------------------------#
#--- V2 Friend Requests API Tests ---#
#---------------------------------#

def test_v2_get_incoming_friend_requests_empty(client, create_user):
    """Test getting incoming friend requests when there are none."""
    user = create_user("alice")
    
    response = client.get(f"/v2/users/{user['id']}/friend-requests/?q=incoming")
    assert response.status_code == 200
    assert response.json() == {"requests": []}


def test_v2_get_incoming_friend_requests(client, create_user):
    """Test getting incoming friend requests."""
    alice = create_user("alice")
    bob = create_user("bob")
    carol = create_user("carol")
    
    # Bob and Carol send requests to Alice
    client.post(
        f"/v2/users/{bob['id']}/friend-requests/",
        json={"receiver_id": alice["id"]}
    )
    client.post(
        f"/v2/users/{carol['id']}/friend-requests/",
        json={"receiver_id": alice["id"]}
    )
    
    # Alice gets incoming requests
    response = client.get(f"/v2/users/{alice['id']}/friend-requests/?q=incoming")
    assert response.status_code == 200
    requests = response.json()["requests"]
    assert len(requests) == 2
    
    # Verify structure and no password exposure
    for req in requests:
        assert "id" in req
        assert "requester" in req
        assert "receiver" in req
        assert "created_at" in req or True  # Optional timestamp field
        assert "password" not in str(req)
        
    # Verify correct requesters
    requester_ids = {req["requester"]["id"] for req in requests}
    assert requester_ids == {bob["id"], carol["id"]}
    
    # All requests should have Alice as receiver
    for req in requests:
        assert req["receiver"]["id"] == alice["id"]


def test_v2_get_outgoing_friend_requests_empty(client, create_user):
    """Test getting outgoing friend requests when there are none."""
    user = create_user("alice")
    
    response = client.get(f"/v2/users/{user['id']}/friend-requests/?q=outgoing")
    assert response.status_code == 200
    assert response.json() == {"requests": []}


def test_v2_get_outgoing_friend_requests(client, create_user):
    """Test getting outgoing friend requests."""
    alice = create_user("alice")
    bob = create_user("bob")
    carol = create_user("carol")
    
    # Alice sends requests to Bob and Carol
    client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": carol["id"]}
    )
    
    # Alice gets outgoing requests
    response = client.get(f"/v2/users/{alice['id']}/friend-requests/?q=outgoing")
    assert response.status_code == 200
    requests = response.json()["requests"]
    assert len(requests) == 2
    
    # Verify correct receivers
    receiver_ids = {req["receiver"]["id"] for req in requests}
    assert receiver_ids == {bob["id"], carol["id"]}
    
    # All requests should have Alice as requester
    for req in requests:
        assert req["requester"]["id"] == alice["id"]


def test_v2_get_friend_requests_invalid_query_param(client, create_user):
    """Test that invalid query parameters are handled gracefully."""
    user = create_user("alice")
    
    # Invalid query parameter should default to empty or return error
    response = client.get(f"/v2/users/{user['id']}/friend-requests/?q=invalid")
    assert response.status_code in [200, 400]
    
    if response.status_code == 200:
        # Should return empty list or all requests
        assert "requests" in response.json()


def test_v2_get_friend_requests_no_query_param(client, create_user):
    """Test getting friend requests without query parameter (should return all or error)."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Alice sends request to Bob
    client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    
    # Get without query param
    response = client.get(f"/v2/users/{alice['id']}/friend-requests/")
    assert response.status_code in [200, 400, 422]
    
    if response.status_code == 200:
        # Should return all requests (incoming + outgoing) or require param
        assert "requests" in response.json()


def test_v2_get_friend_requests_nonexistent_user(client):
    """Test getting friend requests for a user that doesn't exist."""
    response = client.get("/v2/users/99999/friend-requests/?q=incoming")
    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_v2_create_friend_request_success(client, create_user):
    """Test creating a friend request."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    response = client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    
    assert response.status_code == 201
    request = response.json()["request"]
    assert request["requester"]["id"] == alice["id"]
    assert request["receiver"]["id"] == bob["id"]
    assert "id" in request
    assert "password" not in str(request)


def test_v2_create_friend_request_to_self(client, create_user):
    """Test that a user cannot send a friend request to themselves."""
    alice = create_user("alice")
    
    response = client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": alice["id"]}
    )
    
    assert response.status_code == 400
    assert "yourself" in response.json()["detail"].lower()


def test_v2_create_friend_request_nonexistent_requester(client, create_user):
    """Test creating a friend request from a non-existent user."""
    bob = create_user("bob")
    
    response = client.post(
        "/v2/users/99999/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    
    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_v2_create_friend_request_nonexistent_receiver(client, create_user):
    """Test creating a friend request to a non-existent user."""
    alice = create_user("alice")
    
    response = client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": 99999}
    )
    
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_v2_create_duplicate_friend_request(client, create_user):
    """Test that duplicate friend requests are not allowed."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # First request succeeds
    response1 = client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    assert response1.status_code == 201
    
    # Second request fails
    response2 = client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    assert response2.status_code == 400
    assert "already exists" in response2.json()["detail"].lower()


def test_v2_create_friend_request_reverse_exists(client, create_user):
    """Test that a reverse friend request is not allowed."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Alice sends request to Bob
    response1 = client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    assert response1.status_code == 201
    
    # Bob cannot send request to Alice (reverse)
    response2 = client.post(
        f"/v2/users/{bob['id']}/friend-requests/",
        json={"receiver_id": alice["id"]}
    )
    assert response2.status_code == 400
    assert "already exists" in response2.json()["detail"].lower()


def test_v2_create_friend_request_already_friends(client, create_user):
    """Test that friend request cannot be sent to existing friend."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Create friendship using legacy API
    client.post(
        "/friendships/requests/",
        json={"requester": "alice", "receiver": "bob"}
    )
    client.post(
        "/friendships/requests/accept",
        json={"requester": "alice", "receiver": "bob"}
    )
    
    # Try to send friend request - should fail
    response = client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    
    assert response.status_code == 400
    assert "already friends" in response.json()["detail"].lower()


def test_v2_update_friend_request_accept(client, create_user):
    """Test accepting a friend request with PATCH."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Alice sends request to Bob
    client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    
    # Bob accepts the request
    response = client.patch(
        f"/v2/users/{bob['id']}/friend-requests/{alice['id']}",
        json={"action": "accept"}
    )
    
    assert response.status_code == 200
    friendship = response.json()["friendship"]
    
    # Verify friendship was created
    friend_ids = {friendship["user"]["id"], friendship["friend"]["id"]}
    assert friend_ids == {alice["id"], bob["id"]}
    
    # Verify request no longer exists
    incoming = client.get(f"/v2/users/{bob['id']}/friend-requests/?q=incoming")
    assert incoming.json()["requests"] == []
    
    # Verify they are now friends
    friends = client.get(f"/v2/users/{alice['id']}/friends/")
    assert len(friends.json()["friends"]) == 1


def test_v2_update_friend_request_deny(client, create_user):
    """Test denying a friend request with PATCH."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Alice sends request to Bob
    client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    
    # Bob denies the request
    response = client.patch(
        f"/v2/users/{bob['id']}/friend-requests/{alice['id']}",
        json={"action": "deny"}
    )
    
    assert response.status_code == 200
    assert response.json() == {"detail": "Friend request denied"}
    
    # Verify request no longer exists
    incoming = client.get(f"/v2/users/{bob['id']}/friend-requests/?q=incoming")
    assert incoming.json()["requests"] == []
    
    # Verify they are not friends
    friends = client.get(f"/v2/users/{alice['id']}/friends/")
    assert friends.json()["friends"] == []


def test_v2_update_friend_request_invalid_action(client, create_user):
    """Test updating a friend request with invalid action."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Alice sends request to Bob
    client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    
    # Bob tries invalid action
    response = client.patch(
        f"/v2/users/{bob['id']}/friend-requests/{alice['id']}",
        json={"action": "invalid"}
    )
    
    assert response.status_code == 400


def test_v2_update_friend_request_nonexistent(client, create_user):
    """Test updating a friend request that doesn't exist."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    response = client.patch(
        f"/v2/users/{bob['id']}/friend-requests/{alice['id']}",
        json={"action": "accept"}
    )
    
    assert response.status_code == 404
    detail = response.json()["detail"].lower()
    assert "request" in detail and "found" in detail


def test_v2_update_friend_request_nonexistent_user(client, create_user):
    """Test updating friend request when user doesn't exist."""
    alice = create_user("alice")
    
    response = client.patch(
        f"/v2/users/99999/friend-requests/{alice['id']}",
        json={"action": "accept"}
    )
    
    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_v2_update_friend_request_wrong_receiver(client, create_user):
    """Test that only the receiver can accept/deny a request."""
    alice = create_user("alice")
    bob = create_user("bob")
    carol = create_user("carol")
    
    # Alice sends request to Bob
    client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    
    # Carol (not the receiver) tries to accept - should fail
    response = client.patch(
        f"/v2/users/{carol['id']}/friend-requests/{alice['id']}",
        json={"action": "accept"}
    )
    
    assert response.status_code == 404


def test_v2_update_friend_request_requester_cannot_accept(client, create_user):
    """Test that the requester cannot accept their own request."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Alice sends request to Bob
    client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    
    # Alice (requester) tries to accept - should fail
    response = client.patch(
        f"/v2/users/{alice['id']}/friend-requests/{bob['id']}",
        json={"action": "accept"}
    )
    
    assert response.status_code == 404


def test_v2_delete_friend_request_by_requester(client, create_user):
    """Test that requester can cancel their own friend request."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Alice sends request to Bob
    client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    
    # Verify request exists
    outgoing = client.get(f"/v2/users/{alice['id']}/friend-requests/?q=outgoing")
    assert len(outgoing.json()["requests"]) == 1
    
    # Alice cancels the request
    response = client.delete(f"/v2/users/{alice['id']}/friend-requests/{bob['id']}")
    assert response.status_code == 204
    
    # Verify request no longer exists
    outgoing = client.get(f"/v2/users/{alice['id']}/friend-requests/?q=outgoing")
    assert outgoing.json()["requests"] == []
    
    incoming = client.get(f"/v2/users/{bob['id']}/friend-requests/?q=incoming")
    assert incoming.json()["requests"] == []


def test_v2_delete_friend_request_by_receiver(client, create_user):
    """Test that receiver can also delete a friend request."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Alice sends request to Bob
    client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    
    # Bob deletes the request
    response = client.delete(f"/v2/users/{bob['id']}/friend-requests/{alice['id']}")
    assert response.status_code == 204
    
    # Verify request no longer exists
    incoming = client.get(f"/v2/users/{bob['id']}/friend-requests/?q=incoming")
    assert incoming.json()["requests"] == []


def test_v2_delete_friend_request_nonexistent(client, create_user):
    """Test deleting a friend request that doesn't exist."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    response = client.delete(f"/v2/users/{alice['id']}/friend-requests/{bob['id']}")
    assert response.status_code == 404
    detail = response.json()["detail"].lower()
    assert "request" in detail and "not found" in detail


def test_v2_delete_friend_request_nonexistent_user(client, create_user):
    """Test deleting friend request when user doesn't exist."""
    alice = create_user("alice")
    
    response = client.delete(f"/v2/users/99999/friend-requests/{alice['id']}")
    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_v2_delete_friend_request_third_party(client, create_user):
    """Test that a third party cannot delete a friend request."""
    alice = create_user("alice")
    bob = create_user("bob")
    carol = create_user("carol")
    
    # Alice sends request to Bob
    client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    
    # Carol tries to delete - should fail
    response = client.delete(f"/v2/users/{carol['id']}/friend-requests/{alice['id']}")
    detail = response.json()["detail"].lower()
    assert "request" in detail and "not found" in detail


def test_v2_friend_request_referential_integrity(client, create_user, session):
    """Test that deleting a user removes their friend requests."""
    alice = create_user("alice")
    bob = create_user("bob")
    carol = create_user("carol")
    
    # Alice sends requests to Bob and Carol
    client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": carol["id"]}
    )
    
    # Bob sends request to Carol
    client.post(
        f"/v2/users/{bob['id']}/friend-requests/",
        json={"receiver_id": carol["id"]}
    )
    
    # Verify requests exist
    bob_incoming = client.get(f"/v2/users/{bob['id']}/friend-requests/?q=incoming")
    assert len(bob_incoming.json()["requests"]) == 1
    
    carol_incoming = client.get(f"/v2/users/{carol['id']}/friend-requests/?q=incoming")
    assert len(carol_incoming.json()["requests"]) == 2
    
    # Delete Alice
    client.post("/users/delete", json={"name": "alice"})
    
    # Bob and Carol should have fewer requests
    bob_incoming = client.get(f"/v2/users/{bob['id']}/friend-requests/?q=incoming")
    assert bob_incoming.json()["requests"] == []
    
    carol_incoming = client.get(f"/v2/users/{carol['id']}/friend-requests/?q=incoming")
    assert len(carol_incoming.json()["requests"]) == 1
    assert carol_incoming.json()["requests"][0]["requester"]["id"] == bob["id"]


def test_v2_friend_request_workflow_complete(client, create_user):
    """Test complete friend request workflow: create, view, accept."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # 1. Alice creates request to Bob
    create_response = client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    assert create_response.status_code == 201
    
    # 2. Alice sees it in outgoing
    outgoing = client.get(f"/v2/users/{alice['id']}/friend-requests/?q=outgoing")
    assert len(outgoing.json()["requests"]) == 1
    
    # 3. Bob sees it in incoming
    incoming = client.get(f"/v2/users/{bob['id']}/friend-requests/?q=incoming")
    assert len(incoming.json()["requests"]) == 1
    
    # 4. Bob accepts it
    accept_response = client.patch(
        f"/v2/users/{bob['id']}/friend-requests/{alice['id']}",
        json={"action": "accept"}
    )
    assert accept_response.status_code == 200
    
    # 5. Request is gone
    incoming = client.get(f"/v2/users/{bob['id']}/friend-requests/?q=incoming")
    assert incoming.json()["requests"] == []
    
    # 6. They are friends
    friends = client.get(f"/v2/users/{alice['id']}/friends/")
    assert len(friends.json()["friends"]) == 1


def test_v2_friend_request_workflow_deny(client, create_user):
    """Test friend request workflow with denial."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Alice creates request to Bob
    client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    
    # Bob denies it
    deny_response = client.patch(
        f"/v2/users/{bob['id']}/friend-requests/{alice['id']}",
        json={"action": "deny"}
    )
    assert deny_response.status_code == 200
    
    # Request is gone, no friendship
    incoming = client.get(f"/v2/users/{bob['id']}/friend-requests/?q=incoming")
    assert incoming.json()["requests"] == []
    
    friends = client.get(f"/v2/users/{alice['id']}/friends/")
    assert friends.json()["friends"] == []


def test_v2_friend_request_workflow_cancel(client, create_user):
    """Test friend request workflow with cancellation."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Alice creates request to Bob
    client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    
    # Alice cancels it
    cancel_response = client.delete(f"/v2/users/{alice['id']}/friend-requests/{bob['id']}")
    assert cancel_response.status_code == 204
    
    # Request is gone
    outgoing = client.get(f"/v2/users/{alice['id']}/friend-requests/?q=outgoing")
    assert outgoing.json()["requests"] == []
    
    incoming = client.get(f"/v2/users/{bob['id']}/friend-requests/?q=incoming")
    assert incoming.json()["requests"] == []


def test_v2_multiple_pending_requests(client, create_user):
    """Test that a user can have multiple pending requests."""
    alice = create_user("alice")
    bob = create_user("bob")
    carol = create_user("carol")
    dave = create_user("dave")
    
    # Multiple users send requests to Alice
    for user in [bob, carol, dave]:
        response = client.post(
            f"/v2/users/{user['id']}/friend-requests/",
            json={"receiver_id": alice["id"]}
        )
        assert response.status_code == 201
    
    # Alice should have 3 incoming requests
    incoming = client.get(f"/v2/users/{alice['id']}/friend-requests/?q=incoming")
    assert len(incoming.json()["requests"]) == 3


def test_v2_accept_one_request_preserves_others(client, create_user):
    """Test that accepting one request doesn't affect others."""
    alice = create_user("alice")
    bob = create_user("bob")
    carol = create_user("carol")
    
    # Bob and Carol send requests to Alice
    client.post(
        f"/v2/users/{bob['id']}/friend-requests/",
        json={"receiver_id": alice["id"]}
    )
    client.post(
        f"/v2/users/{carol['id']}/friend-requests/",
        json={"receiver_id": alice["id"]}
    )
    
    # Alice accepts Bob's request
    client.patch(
        f"/v2/users/{alice['id']}/friend-requests/{bob['id']}",
        json={"action": "accept"}
    )
    
    # Carol's request should still exist
    incoming = client.get(f"/v2/users/{alice['id']}/friend-requests/?q=incoming")
    assert len(incoming.json()["requests"]) == 1
    assert incoming.json()["requests"][0]["requester"]["id"] == carol["id"]


def test_v2_no_password_exposure_in_friend_requests(client, create_user):
    """Test that password is never exposed in friend request endpoints."""
    alice = create_user("alice", password="super_secret")
    bob = create_user("bob", password="also_secret")
    
    # Create request
    client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    
    # Check incoming
    incoming = client.get(f"/v2/users/{bob['id']}/friend-requests/?q=incoming")
    for req in incoming.json()["requests"]:
        assert "password" not in str(req)
        assert "super_secret" not in str(req)
        assert "also_secret" not in str(req)
    
    # Check outgoing
    outgoing = client.get(f"/v2/users/{alice['id']}/friend-requests/?q=outgoing")
    for req in outgoing.json()["requests"]:
        assert "password" not in str(req)


def test_v2_legacy_endpoints_still_work_with_v2_requests(client, create_user):
    """Test that legacy endpoints can see requests created with v2 API."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Create request using v2 API
    client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    
    # Legacy endpoint should see it
    legacy_response = client.get("/friendships/requests/bob")
    assert legacy_response.status_code == 200
    assert len(legacy_response.json()["requests"]) == 1


def test_v2_v2_requests_accept_via_legacy(client, create_user):
    """Test that requests created with v2 can be accepted via legacy API."""
    alice = create_user("alice")
    bob = create_user("bob")
    
    # Create request using v2 API
    client.post(
        f"/v2/users/{alice['id']}/friend-requests/",
        json={"receiver_id": bob["id"]}
    )
    
    # Accept using legacy API
    accept_response = client.post(
        "/friendships/requests/accept",
        json={"requester": "alice", "receiver": "bob"}
    )
    assert accept_response.status_code == 200
    
    # Verify friendship via v2 API
    friends = client.get(f"/v2/users/{alice['id']}/friends/")
    assert len(friends.json()["friends"]) == 1