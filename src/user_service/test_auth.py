import hashlib
import time

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, text

from .models.user import Base, UserRepository, get_user_repository
from .api import app, _rate_windows


import pytest


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
    # ensure the global in-memory rate limiter is reset per test
    _rate_windows.clear()
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
        return {"id": user_id, "name": name, "email": data["email"], "password": password}

    return _create


def test_issue_token_and_rate_limit(client, create_user):
    user = create_user("alice", password="alicepw")

    # issue token
    resp = client.post(
        "/v2/authentications/",
        json={"name": user["name"], "password": user["password"], "expiry": "2099-01-01 00:00:00"},
    )
    assert resp.status_code == 201
    token = resp.json()["jwt"]

    # two requests allowed for tier=1 (2*tier)
    h = {"Authorization": f"Bearer {token}"}
    r1 = client.get(f"/users/{user['name']}", headers=h)
    assert r1.status_code == 200
    r2 = client.get(f"/users/{user['name']}", headers=h)
    assert r2.status_code == 200
    # third should be rate-limited
    r3 = client.get(f"/users/{user['name']}", headers=h)
    assert r3.status_code == 429


def test_issue_second_token_invalidates_first(client, create_user):
    user = create_user("bob", password="bobpw")

    r1 = client.post(
        "/v2/authentications/",
        json={"name": user["name"], "password": user["password"], "expiry": "2099-01-01 00:00:00"},
    )
    assert r1.status_code == 201
    token1 = r1.json()["jwt"]

    # issue a second token (this should invalidate the first)
    r2 = client.post(
        "/v2/authentications/",
        json={"name": user["name"], "password": user["password"], "expiry": "2099-01-01 00:00:00"},
    )
    assert r2.status_code == 201
    token2 = r2.json()["jwt"]

    # using token1 should now behave as unauthenticated -> only 1 request allowed per 10s for IP
    h1 = {"Authorization": f"Bearer {token1}"}
    r_a = client.get(f"/users/{user['name']}", headers=h1)
    assert r_a.status_code == 200
    r_b = client.get(f"/users/{user['name']}", headers=h1)
    assert r_b.status_code == 429

    # token2 should still work for 2 requests
    h2 = {"Authorization": f"Bearer {token2}"}
    r_c = client.get(f"/users/{user['name']}", headers=h2)
    assert r_c.status_code == 200
    r_d = client.get(f"/users/{user['name']}", headers=h2)
    assert r_d.status_code == 200
    r_e = client.get(f"/users/{user['name']}", headers=h2)
    assert r_e.status_code == 429
