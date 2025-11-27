from __future__ import annotations

import pytest
import asyncio
import fakeredis.aioredis
from starlette.requests import Request

from src.event_service.repository import EventRepository
import src.event_service.logging as event_logging


DATETIME_FMT = "%Y-%m-%d %H:%M:%S"


@pytest.fixture()
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture()
def event_repo(fake_redis):
    return EventRepository(fake_redis)


@pytest.fixture(autouse=True)
def patch_get_redis(monkeypatch, fake_redis):
    """
    Ensure RequestEventLogger writes to our fake Redis, not the real one.
    """
    monkeypatch.setattr(event_logging, "get_redis", lambda: fake_redis)
    yield


def _build_request(path: str = "/v2/users/", method: str = "GET") -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "client": ("127.0.0.1", 8000),
        "scheme": "http",
        "server": ("testserver", 80),
        "query_string": b"",
    }
    req = Request(scope)
    return req


@pytest.mark.asyncio
async def test_log_request_creates_api_request_event_with_latency(event_repo: EventRepository):
    req = _build_request("/v2/users/")
    # Simulate authenticated user
    req.state.user_id = "user-123"

    logger = event_logging.RequestEventLogger()
    await logger.log_request(req, 200, latency_ms=123.456)

    events = await event_repo.query(
        event_type="api.request",
        source=None,
        user=None,
        after=None,
        before=None,
        limit=10,
    )
    # We expect exactly one logged request
    assert len(events) == 1
    ev = events[0]

    assert ev.type == "api.request"
    assert ev.user == "user-123"
    assert ev.payload["method"] == "GET"
    assert ev.payload["status_code"] == 200
    # latency_ms should be present and roughly what we passed
    assert ev.payload["latency_ms"] == pytest.approx(123.456)


@pytest.mark.asyncio
async def test_static_requests_are_ignored(event_repo: EventRepository):
    req = _build_request("/static/app.js")
    logger = event_logging.RequestEventLogger()
    await logger.log_request(req, 200, latency_ms=10.0)

    events = await event_repo.query(
        event_type=None,
        source=None,
        user=None,
        after=None,
        before=None,
        limit=10,
    )
    # Nothing should have been logged for static assets
    assert events == []
