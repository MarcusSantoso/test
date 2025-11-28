from __future__ import annotations

import sys
import types
import asyncio
from datetime import datetime

import pytest
import fakeredis.aioredis

# --- Stub src.shared.ai_summarization_engine if missing -----------------------

if "src.shared.ai_summarization_engine" not in sys.modules:
    ai_mod = types.ModuleType("src.shared.ai_summarization_engine")

    class MissingAPIKey(Exception):
        pass

    class MissingOpenAIClient(Exception):
        pass

    def get_summarization_engine():
        raise MissingOpenAIClient("AI engine not available in test environment")

    ai_mod.MissingAPIKey = MissingAPIKey
    ai_mod.MissingOpenAIClient = MissingOpenAIClient
    ai_mod.get_summarization_engine = get_summarization_engine

    sys.modules["src.shared.ai_summarization_engine"] = ai_mod

# NOTE: we do NOT stub src.event_service.usage_analytics; real module exists.

# Now import main
import src.admin.main as admin  # noqa: E402
from src.event_service.repository import EventRepository


@pytest.fixture()
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture()
def event_repo(fake_redis):
    return EventRepository(fake_redis)


def test_log_admin_event_with_user(event_repo: EventRepository):
    """_log_admin_event should write a well-formed event when user_id is provided."""
    async def _run():
        await admin._log_admin_event(
            event_repo,
            event_type="admin.test_event",
            payload={"action": "demo"},
            user_id=123,
            source="/admin/test",
        )

        events = await event_repo.query(
            event_type="admin.test_event",
            source="/admin/test",
            user="123",
            after=None,
            before=None,
            limit=10,
        )
        assert len(events) == 1
        ev = events[0]
        assert ev.type == "admin.test_event"
        assert ev.source == "/admin/test"
        assert ev.user == "123"
        assert ev.payload == {"action": "demo"}
        # when should be a datetime object
        assert isinstance(ev.when, datetime)

    asyncio.run(_run())


def test_log_admin_event_without_user(event_repo: EventRepository):
    """_log_admin_event should handle user_id=None and store user as None."""
    async def _run():
        await admin._log_admin_event(
            event_repo,
            event_type="admin.no_user",
            payload={"action": "demo2"},
            user_id=None,
            source="/admin",
        )

        events = await event_repo.query(
            event_type="admin.no_user",
            source="/admin",
            user=None,
            after=None,
            before=None,
            limit=10,
        )
        assert len(events) == 1
        ev = events[0]
        assert ev.type == "admin.no_user"
        assert ev.source == "/admin"
        assert ev.user is None
        assert ev.payload == {"action": "demo2"}
        # when should also be a datetime here
        assert isinstance(ev.when, datetime)

    asyncio.run(_run())
