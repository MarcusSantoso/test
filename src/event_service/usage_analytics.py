from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, List
from collections import Counter

from .repository import EventRepository


@dataclass
class DailyUsageRow:
    day: date
    total_searches: int = 0
    professor_searches: int = 0
    course_searches: int = 0
    active_users: int = 0


@dataclass
class TopEntityRow:
    name: str
    count: int


@dataclass
class PerformanceStats:
    requests_total: int = 0
    errors_total: int = 0
    latency_avg_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_max_ms: float = 0.0

    @property
    def error_rate_pct(self) -> float:
        if not self.requests_total:
            return 0.0
        return (self.errors_total / self.requests_total) * 100.0


@dataclass
class UsageSummary:
    daily: List[DailyUsageRow]
    top_professors: List[TopEntityRow]
    performance: PerformanceStats


class UsageAnalyticsService:
    """
    Aggregates usage & performance metrics from the `events` stream.

    Expected event types / payloads:

    - search.professor / search.course:
        payload:
            query: str
            kind: "professor" | "course"
            results_count: int
            prof_names / prof_ids (optional)
            course_codes (optional)
        user id is taken from event.user (string)

    - api.request:
        payload:
            latency_ms: float
            status_code: int
            path, method (optional)
    """

    def __init__(self, repo: EventRepository):
        self.repo = repo

    # ---- public API ----

    async def last_n_days(self, n: int = 7) -> UsageSummary:
        """Return aggregate usage/performance stats for the last n days (inclusive of today)."""
        if n < 1:
            n = 1
        today = self._today()
        start_day = today - timedelta(days=n - 1)
        return await self.range(start_day, today)

    async def range(self, start_day: date, end_day: date) -> UsageSummary:
        """Aggregate stats from start_day to end_day inclusive."""
        if end_day < start_day:
            start_day, end_day = end_day, start_day

        days: list[date] = []
        cur = start_day
        while cur <= end_day:
            days.append(cur)
            cur += timedelta(days=1)

        window_start = self._day_start(start_day)
        window_end = self._day_start(end_day + timedelta(days=1))

        daily_rows = await self._daily_usage(days)
        top_professors = await self._top_professors(window_start, window_end, limit=10)
        perf = await self._performance(window_start, window_end)

        return UsageSummary(daily=daily_rows, top_professors=top_professors, performance=perf)

    # ---- daily usage helpers ----

    async def _daily_usage(self, days: Iterable[date]) -> List[DailyUsageRow]:
        rows: list[DailyUsageRow] = []
        for day in days:
            start = self._day_start(day)
            end = start + timedelta(days=1)

            prof_events = await self.repo.query(
                event_type="search.professor",
                after=start,
                before=end,
                limit=10000,
            )
            course_events = await self.repo.query(
                event_type="search.course",
                after=start,
                before=end,
                limit=10000,
            )

            total_searches = len(prof_events) + len(course_events)
            professor_searches = len(prof_events)
            course_searches = len(course_events)

            user_ids: set[str] = set()
            for ev in list(prof_events) + list(course_events):
                user_val = getattr(ev, "user", None)
                if user_val:
                    user_ids.add(str(user_val))

            rows.append(
                DailyUsageRow(
                    day=day,
                    total_searches=total_searches,
                    professor_searches=professor_searches,
                    course_searches=course_searches,
                    active_users=len(user_ids),
                )
            )
        return rows

    # ---- top professors ----

    async def _top_professors(
        self,
        start: datetime,
        end: datetime,
        limit: int = 10,
    ) -> List[TopEntityRow]:
        events = await self.repo.query(
            event_type="search.professor",
            after=start,
            before=end,
            limit=50000,
        )
        counter: Counter[str] = Counter()

        for ev in events:
            payload = getattr(ev, "payload", None) or {}
            name = (
                (payload.get("prof_name")
                 or payload.get("professor_name")
                 or "").strip()
            )
            if not name:
                name = (payload.get("prof_names") or [""])[0] if isinstance(
                    payload.get("prof_names"), list
                ) else ""
                name = name.strip()
            if not name:
                name = (payload.get("query") or "").strip()
            if not name:
                continue
            counter[name] += 1

        return [
            TopEntityRow(name=name, count=count)
            for name, count in counter.most_common(limit)
        ]

    # ---- performance stats ----

    async def _performance(self, start: datetime, end: datetime) -> PerformanceStats:
        events = await self.repo.query(
            event_type="api.request",
            after=start,
            before=end,
            limit=50000,
        )
        if not events:
            return PerformanceStats()

        latencies: list[float] = []
        error_count = 0

        for ev in events:
            payload = getattr(ev, "payload", None) or {}
            val = payload.get("latency_ms")
            if isinstance(val, (int, float)):
                latencies.append(float(val))
            status = payload.get("status_code") or getattr(ev, "status_code", None)
            try:
                status_int = int(status)
            except Exception:
                status_int = None
            if status_int is not None and status_int >= 400:
                error_count += 1

        latencies.sort()
        requests_total = len(events)
        avg = sum(latencies) / len(latencies) if latencies else 0.0
        p95 = self._percentile(latencies, 0.95) if latencies else 0.0
        max_val = latencies[-1] if latencies else 0.0

        return PerformanceStats(
            requests_total=requests_total,
            errors_total=error_count,
            latency_avg_ms=round(avg, 3),
            latency_p95_ms=round(p95, 3),
            latency_max_ms=round(max_val, 3),
        )

    # ---- utility methods ----

    @staticmethod
    def _today() -> date:
        return datetime.now().date()

    @staticmethod
    def _day_start(d: date) -> datetime:
        return datetime.combine(d, time.min)

    @staticmethod
    def _percentile(sorted_values: List[float], percentile: float) -> float:
        if not sorted_values:
            return 0.0
        if len(sorted_values) == 1:
            return sorted_values[0]
        k = (len(sorted_values) - 1) * percentile
        f = int(k)
        c = min(f + 1, len(sorted_values) - 1)
        if f == c:
            return sorted_values[f]
        d0 = sorted_values[f] * (c - k)
        d1 = sorted_values[c] * (k - f)
        return d0 + d1
