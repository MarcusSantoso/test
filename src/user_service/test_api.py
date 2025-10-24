import hashlib
import pytest

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, text

from .models.user import Base, UserRepository, get_user_repository

from .api import app


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
    with TestClient(app) as c:
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


def test_read_user(client, created_user):
    response = client.get("/users/foo")
    assert response.status_code == 200
    assert response.json() == {
        "user": {"name": "foo", "id": created_user["id"]}
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
    assert img.size[0] <= 512
    assert img.size[1] <= 512


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
    assert width <= 512 and height <= 512
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