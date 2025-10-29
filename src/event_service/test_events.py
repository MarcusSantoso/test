from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
import fakeredis.aioredis

from src.event_service.repository import EventRepository, get_event_repository
from src.user_service.api import app

DATETIME_FMT = "%Y-%m-%d %H:%M:%S"


@pytest.fixture()
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture()
def event_repo(fake_redis):
    yield EventRepository(fake_redis)


@pytest.fixture()
def client(event_repo):
    app.dependency_overrides[get_event_repository] = lambda: event_repo
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_event_repository, None)


def _ts(day: date, hour: int, minute: int) -> str:
    return datetime.combine(day, time(hour=hour, minute=minute)).strftime(DATETIME_FMT)


def create_event(client: TestClient, when: str, event_type: str, user: str | None):
    payload = {
        "when": when,
        "source": "http://localhost/example",
        "type": event_type,
        "payload": {"example": True},
        "user": user,
    }
    response = client.post("/v2/events/", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["event"]


def test_create_and_filter_events(client):
    when_first = "2025-01-01 10:00:00"
    when_second = "2025-01-01 12:00:00"

    first = {
        "when": when_first,
        "source": "http://localhost/blog/one",
        "type": "text-highlight",
        "payload": {"content": "hello"},
        "user": "abc-123",
    }
    second = {
        "when": when_second,
        "source": "http://localhost/blog/two",
        "type": "link-out",
        "payload": {"destination": "https://example.com"},
        "user": None,
    }

    resp_first = client.post("/v2/events/", json=first)
    assert resp_first.status_code == 201
    body = resp_first.json()["event"]
    assert body["type"] == first["type"]
    assert body["user"] == first["user"]

    resp_second = client.post("/v2/events/", json=second)
    assert resp_second.status_code == 201

    resp_all = client.get("/v2/events/")
    assert resp_all.status_code == 200
    assert len(resp_all.json()["events"]) == 2

    resp_filtered = client.get(
        "/v2/events/",
        params={
            "type": "text-highlight",
            "after": "2025-01-01 09:00:00",
            "before": "2025-01-01 11:00:00",
        },
    )
    events = resp_filtered.json()["events"]
    assert len(events) == 1
    assert events[0]["type"] == "text-highlight"
    assert events[0]["when"] == when_first


def test_analytics_on_specific_day(client, monkeypatch):
    monkeypatch.setenv("AUTH_TTL_SECONDS", "300")
    target_day = datetime.now(timezone.utc).date() - timedelta(days=1)

    create_event(client, _ts(target_day, 10, 0), "view", "user-a")
    create_event(client, _ts(target_day, 10, 4), "view", "user-a")
    create_event(client, _ts(target_day, 10, 20), "view", "user-a")
    create_event(client, _ts(target_day, 10, 2), "view", "user-b")
    create_event(client, _ts(target_day, 23, 50), "view", "user-c")

    response = client.get(f"/v2/analytics?on={target_day.isoformat()}")
    assert response.status_code == 200
    data = response.json()

    expected_session = {
        "min": 300.0,
        "max": 540.0,
        "mean": 360.0,
        "median": 300.0,
        "p95": 504.0,
    }
    for key, value in expected_session.items():
        assert data["session_length"][key] == pytest.approx(value)

    assert data["active_users"]["current"] == pytest.approx(0.0)
    assert data["active_users"]["max"] == pytest.approx(2.0)


def test_analytics_since_computes_mean(client, monkeypatch):
    monkeypatch.setenv("AUTH_TTL_SECONDS", "300")
    today = datetime.now(timezone.utc).date()
    start_day = today - timedelta(days=1)

    # Day 1 events (start_day)
    create_event(client, _ts(start_day, 10, 0), "view", "user-a")
    create_event(client, _ts(start_day, 10, 4), "view", "user-a")
    create_event(client, _ts(start_day, 10, 20), "view", "user-a")
    create_event(client, _ts(start_day, 10, 2), "view", "user-b")
    create_event(client, _ts(start_day, 23, 50), "view", "user-c")

    # Day 2 events (today)
    create_event(client, _ts(today, 9, 0), "view", "user-a")
    create_event(client, _ts(today, 9, 3), "view", "user-b")
    create_event(client, _ts(today, 9, 8), "view", "user-b")
    create_event(client, _ts(today, 12, 0), "view", "user-c")

    response = client.get(f"/v2/analytics?since={start_day.isoformat()}")
    assert response.status_code == 200
    data = response.json()

    expected_session = {
        "min": 300.0,
        "max": 570.0,
        "mean": 380.0,
        "median": 300.0,
        "p95": 537.0,
    }
    for key, value in expected_session.items():
        assert data["session_length"][key] == pytest.approx(value)

    assert data["active_users"]["current"] == pytest.approx(0.0)
    assert data["active_users"]["max"] == pytest.approx(2.0)
