from __future__ import annotations

import pytest
import fakeredis.aioredis
from datetime import datetime, timedelta, timezone, date

from src.event_service.repository import EventRepository
from src.event_service.schemas import EventCreateSchema
from src.event_service.usage_analytics import (
    UsageAnalyticsService,
    DailyUsageRow,
    TopEntityRow,
    PerformanceStats,
)
import src.event_service.usage_analytics as usage_mod


@pytest.fixture()
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture()
def event_repo(fake_redis):
    return EventRepository(fake_redis)


def _dt(days_ago: int = 0) -> str:
    """Helper to generate event timestamps in UTC for the mock repo."""
    d = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return d.strftime("%Y-%m-%d %H:%M:%S")


@pytest.mark.asyncio
async def test_daily_search_counts(event_repo: EventRepository):
    """
    Verify that the UsageAnalyticsService correctly counts daily
    professor and course search events.
    """
    today = date.today()
    yesterday = today - timedelta(days=1)

    # Create events: 3 professor searches yesterday, 1 course search today
    events = [
        EventCreateSchema(
            when=_dt(days_ago=1),
            source="/v2/search",
            type="search.professor",
            payload={"query": "smith", "kind": "professor"},
            user="u1",
        ),
        EventCreateSchema(
            when=_dt(days_ago=1),
            source="/v2/search",
            type="search.professor",
            payload={"query": "smith", "kind": "professor"},
            user="u2",
        ),
        EventCreateSchema(
            when=_dt(days_ago=1),
            source="/v2/search",
            type="search.professor",
            payload={"query": "jones", "kind": "professor"},
            user="u1",
        ),
        EventCreateSchema(
            when=_dt(days_ago=0),
            source="/v2/search",
            type="search.course",
            payload={"query": "cmpt 225", "kind": "course"},
            user="u3",
        ),
    ]

    for e in events:
        await event_repo.create(e)

    service = UsageAnalyticsService(event_repo)
    summary = await service.last_n_days(2)
    daily = summary.daily

    assert len(daily) == 2

    # Sort to match oldest -> newest
    daily_sorted = sorted(daily, key=lambda r: r.day)

    # Yesterday row
    row_y = daily_sorted[0]
    assert isinstance(row_y, DailyUsageRow)
    assert row_y.professor_searches == 3
    assert row_y.course_searches == 0
    assert row_y.total_searches == 3
    # Active users yesterday: u1 and u2 -> 2
    assert row_y.active_users == 2

    # Today row
    row_t = daily_sorted[1]
    assert row_t.professor_searches == 0
    assert row_t.course_searches == 1
    assert row_t.total_searches == 1
    assert row_t.active_users == 1  # u3


@pytest.mark.asyncio
async def test_top_professors(event_repo: EventRepository):
    """
    Verify correct top professor ranking aggregation.
    """
    # Two professors appear multiple times across two days.
    events = [
        EventCreateSchema(
            when=_dt(1),
            source="/v2/search",
            type="search.professor",
            payload={"prof_name": "Dr. A", "kind": "professor"},
            user="u1",
        ),
        EventCreateSchema(
            when=_dt(1),
            source="/v2/search",
            type="search.professor",
            payload={"prof_name": "Dr. A", "kind": "professor"},
            user="u2",
        ),
        EventCreateSchema(
            when=_dt(0),
            source="/v2/search",
            type="search.professor",
            payload={"prof_name": "Dr. B", "kind": "professor"},
            user="u3",
        ),
        EventCreateSchema(
            when=_dt(0),
            source="/v2/search",
            type="search.professor",
            payload={"prof_name": "Dr. A", "kind": "professor"},
            user="u1",
        ),
    ]
    for e in events:
        await event_repo.create(e)

    service = UsageAnalyticsService(event_repo)
    summary = await service.last_n_days(2)

    top = summary.top_professors
    assert len(top) == 2

    # Should be ordered: A then B
    assert top[0].name == "Dr. A"
    assert top[0].count == 3

    assert top[1].name == "Dr. B"
    assert top[1].count == 1


@pytest.mark.asyncio
async def test_performance_stats(event_repo: EventRepository):
    """
    Verify that performance stats aggregate avg, p95, and error rate
    from api.request events.
    """
    events = [
        EventCreateSchema(
            when=_dt(0),
            source="/v2/search",
            type="api.request",
            payload={"latency_ms": 100, "status_code": 200},
            user=None,
        ),
        EventCreateSchema(
            when=_dt(0),
            source="/v2/search",
            type="api.request",
            payload={"latency_ms": 200, "status_code": 200},
            user=None,
        ),
        EventCreateSchema(
            when=_dt(0),
            source="/v2/search",
            type="api.request",
            payload={"latency_ms": 400, "status_code": 500},  # error
            user=None,
        ),
        EventCreateSchema(
            when=_dt(0),
            source="/v2/search",
            type="api.request",
            payload={"latency_ms": 1000, "status_code": 200},
            user=None,
        ),
    ]
    for e in events:
        await event_repo.create(e)

    service = UsageAnalyticsService(event_repo)
    summary = await service.last_n_days(1)

    perf = summary.performance
    assert isinstance(perf, PerformanceStats)

    assert perf.requests_total == 4
    assert perf.errors_total == 1
    assert perf.error_rate_pct == pytest.approx(25.0)

    # Average latency
    assert perf.latency_avg_ms == pytest.approx((100 + 200 + 400 + 1000) / 4)

    # P95 should be between the 3rd and 4th sorted values
    assert perf.latency_p95_ms >= 400
    assert perf.latency_p95_ms <= 1000

    assert perf.latency_max_ms == 1000
