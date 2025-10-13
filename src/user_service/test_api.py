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
