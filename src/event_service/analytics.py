from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import floor, ceil
from statistics import fmean, median
from typing import Iterable

from .repository import EventRepository
from .time_utils import utc_now_naive


def _read_ttl_seconds() -> int:
    raw = os.getenv("AUTH_TTL_SECONDS", "300")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 300
    return max(1, value)


@dataclass
class SessionLengthStats:
    min: float = 0.0
    max: float = 0.0
    mean: float = 0.0
    median: float = 0.0
    p95: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "min": self.min,
            "max": self.max,
            "mean": self.mean,
            "median": self.median,
            "p95": self.p95,
        }


@dataclass
class ActiveUsersStats:
    current: float = 0.0
    max: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {"current": self.current, "max": self.max}


@dataclass
class AnalyticsSnapshot:
    session_length: SessionLengthStats
    active_users: ActiveUsersStats

    def to_dict(self) -> dict[str, dict[str, float]]:
        return {
            "session_length": self.session_length.to_dict(),
            "active_users": self.active_users.to_dict(),
        }


class EventAnalyticsService:
    def __init__(self, repo: EventRepository, ttl_seconds: int | None = None):
        self.repo = repo
        self.ttl_seconds = ttl_seconds or _read_ttl_seconds()
        if self.ttl_seconds < 1:
            self.ttl_seconds = 1
        self.ttl_delta = timedelta(seconds=self.ttl_seconds)

    async def today(self, now: datetime | None = None) -> AnalyticsSnapshot:
        now = now or utc_now_naive()
        return await self._daily_snapshot(now.date(), now)

    async def on(self, target_day: date) -> AnalyticsSnapshot:
        reference = datetime.combine(target_day, time(23, 59, 59))
        return await self._daily_snapshot(target_day, reference)

    async def since(self, start_day: date) -> AnalyticsSnapshot:
        today = utc_now_naive().date()
        if start_day > today:
            return AnalyticsSnapshot(SessionLengthStats(), ActiveUsersStats())

        snapshots: list[AnalyticsSnapshot] = []
        current = start_day
        while current <= today:
            reference = datetime.combine(current, time(23, 59, 59))
            snapshots.append(await self._daily_snapshot(current, reference))
            current += timedelta(days=1)

        return _mean_snapshot(snapshots)

    async def _daily_snapshot(self, day: date, reference_time: datetime) -> AnalyticsSnapshot:
        day_start = datetime.combine(day, time.min)
        if reference_time < day_start:
            return AnalyticsSnapshot(SessionLengthStats(), ActiveUsersStats())

        events = await self.repo.events_between(day_start, reference_time, require_user=True)
        user_events = self._group_events(events)
        sessions = self._build_sessions(user_events)

        session_lengths = [(end - start).total_seconds() for start, end in sessions]
        length_stats = _compute_session_stats(session_lengths)

        current_active = _count_active_at(sessions, reference_time)
        max_active = _max_concurrent_sessions(sessions, day_start, reference_time)
        active_stats = ActiveUsersStats(current=float(current_active), max=float(max_active))

        return AnalyticsSnapshot(length_stats, active_stats)

    def _group_events(self, events) -> dict[str, list[datetime]]:
        grouped: dict[str, list[datetime]] = {}
        for event in events:
            if not event.user:
                continue
            grouped.setdefault(event.user, []).append(event.when)
        for timestamps in grouped.values():
            timestamps.sort()
        return grouped

    def _build_sessions(self, grouped_events: dict[str, list[datetime]]) -> list[tuple[datetime, datetime]]:
        sessions: list[tuple[datetime, datetime]] = []
        for timestamps in grouped_events.values():
            if not timestamps:
                continue
            start = timestamps[0]
            end = start + self.ttl_delta
            for ts in timestamps[1:]:
                if ts <= end:
                    end = ts + self.ttl_delta
                else:
                    sessions.append((start, end))
                    start = ts
                    end = ts + self.ttl_delta
            sessions.append((start, end))
        return sessions


def _compute_session_stats(lengths: Iterable[float]) -> SessionLengthStats:
    data = list(lengths)
    if not data:
        return SessionLengthStats()
    data.sort()
    return SessionLengthStats(
        min=round(data[0], 3),
        max=round(data[-1], 3),
        mean=round(fmean(data), 3),
        median=round(median(data), 3),
        p95=round(_percentile(data, 0.95), 3),
    )


def _percentile(sorted_values: list[float], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * percentile
    lower = floor(k)
    upper = ceil(k)
    if lower == upper:
        return sorted_values[int(k)]
    lower_value = sorted_values[lower] * (upper - k)
    upper_value = sorted_values[upper] * (k - lower)
    return lower_value + upper_value


def _count_active_at(sessions: list[tuple[datetime, datetime]], timestamp: datetime) -> int:
    return sum(1 for start, end in sessions if start <= timestamp < end)


def _max_concurrent_sessions(
    sessions: list[tuple[datetime, datetime]], window_start: datetime, window_end: datetime
) -> int:
    if not sessions:
        return 0
    boundaries: list[tuple[datetime, int, int]] = []
    for start, end in sessions:
        clamped_start = max(start, window_start)
        clamped_end = min(end, window_end)
        if clamped_start >= clamped_end:
            continue
        boundaries.append((clamped_start, 1, 1))
        boundaries.append((clamped_end, -1, 0))
    boundaries.sort(key=lambda item: (item[0], item[2]))
    active = 0
    max_active = 0
    for _, delta, _order in boundaries:
        active += delta
        if active > max_active:
            max_active = active
    return max_active


def _mean_snapshot(snapshots: list[AnalyticsSnapshot]) -> AnalyticsSnapshot:
    if not snapshots:
        return AnalyticsSnapshot(SessionLengthStats(), ActiveUsersStats())

    count = len(snapshots)
    sl_fields = SessionLengthStats.__dataclass_fields__.keys()
    au_fields = ActiveUsersStats.__dataclass_fields__.keys()

    session_values = {
        field: round(
            sum(getattr(snapshot.session_length, field) for snapshot in snapshots) / count,
            3,
        )
        for field in sl_fields
    }
    active_values = {
        field: round(
            sum(getattr(snapshot.active_users, field) for snapshot in snapshots) / count,
            3,
        )
        for field in au_fields
    }

    return AnalyticsSnapshot(
        SessionLengthStats(**session_values),
        ActiveUsersStats(**active_values),
    )
