from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Iterable, Sequence
from urllib.parse import quote_plus

from fastapi import Depends
from redis import asyncio as redis

from src.shared.redis_client import get_redis

from .schemas import EventCreateSchema
from .time_utils import parse_datetime_string


@dataclass(slots=True)
class EventRecord:
    id: int
    when: datetime
    source: str
    type: str
    payload: dict
    user: str | None


EVENT_KEY_PREFIX = "events:item:"
TIMELINE_KEY = "events:by_when"
TYPE_INDEX_PREFIX = "events:type:"
SOURCE_INDEX_PREFIX = "events:source:"
USER_INDEX_PREFIX = "events:user:"
COUNTER_KEY = "events:next_id"


class EventRepository:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    async def create(self, payload: EventCreateSchema) -> EventRecord:
        when = parse_datetime_string(payload.when)
        event_id = int(await self.redis.incr(COUNTER_KEY))
        record = EventRecord(
            id=event_id,
            when=when,
            source=payload.source,
            type=payload.type,
            payload=payload.payload,
            user=payload.user,
        )
        await self._persist(record)
        return record

    async def query(
        self,
        *,
        event_type: str | None = None,
        source: str | None = None,
        before: datetime | None = None,
        after: datetime | None = None,
        user: str | None = None,
        limit: int | None = None,
    ) -> list[EventRecord]:
        min_score = _score(after) if after else "-inf"
        max_score = _score(before) if before else "+inf"

        index_key, needs_post_filter = self._select_index(event_type, source, user)
        fetch_size = None
        if limit and needs_post_filter:
            fetch_size = limit * 5
        elif limit:
            fetch_size = limit

        range_kwargs = {}
        if fetch_size is not None:
            range_kwargs["start"] = 0
            range_kwargs["num"] = fetch_size

        ids = await self.redis.zrangebyscore(index_key, min_score, max_score, **range_kwargs)
        events = await self._hydrate(ids)
        events.sort(key=lambda item: (item.when, item.id))
        filtered = [
            event
            for event in events
            if self._matches_filters(event, event_type, source, user)
        ]
        if limit:
            filtered = filtered[:limit]
        return filtered

    async def events_between(
        self,
        start: datetime,
        end: datetime,
        *,
        require_user: bool = True,
    ) -> Sequence[EventRecord]:
        ids = await self.redis.zrangebyscore(TIMELINE_KEY, _score(start), _score(end))
        events = await self._hydrate(ids)
        events.sort(key=lambda item: (item.when, item.id))
        filtered: list[EventRecord] = []
        for event in events:
            if not (start <= event.when <= end):
                continue
            if require_user and event.user is None:
                continue
            filtered.append(event)
        return filtered

    async def _persist(self, event: EventRecord) -> None:
        payload_json = json.dumps(event.payload, ensure_ascii=True, separators=(",", ":"))
        when_str = event.when.strftime("%Y-%m-%d %H:%M:%S")
        event_key = _event_key(event.id)

        await self.redis.hset(
            event_key,
            mapping={
                "id": str(event.id),
                "when": when_str,
                "source": event.source,
                "type": event.type,
                "payload": payload_json,
                "user": event.user or "",
                "user_is_null": "1" if event.user is None else "0",
            },
        )

        score = _score(event.when)
        await self.redis.zadd(TIMELINE_KEY, {event.id: score})
        await self.redis.zadd(_type_index_key(event.type), {event.id: score})
        await self.redis.zadd(_source_index_key(event.source), {event.id: score})
        if event.user is not None:
            await self.redis.zadd(_user_index_key(event.user), {event.id: score})

    async def _hydrate(self, ids: Iterable[str]) -> list[EventRecord]:
        event_ids = [int(event_id) for event_id in ids]
        if not event_ids:
            return []
        pipe = self.redis.pipeline(transaction=False)
        for event_id in event_ids:
            pipe.hgetall(_event_key(event_id))
        raw_events = await pipe.execute()

        events: list[EventRecord] = []
        for event_id, data in zip(event_ids, raw_events):
            if not data:
                continue
            events.append(_deserialize_event(event_id, data))
        return events

    @staticmethod
    def _matches_filters(
        event: EventRecord,
        event_type: str | None,
        source: str | None,
        user: str | None,
    ) -> bool:
        if event_type and event.type != event_type:
            return False
        if source and event.source != source:
            return False
        if user is not None and event.user != user:
            return False
        return True

    @staticmethod
    def _select_index(
        event_type: str | None,
        source: str | None,
        user: str | None,
    ) -> tuple[str, bool]:
        """Choose the narrowest Redis index and indicate if post-filtering is required."""
        if user is not None:
            return _user_index_key(user), bool(event_type or source)
        if event_type:
            return _type_index_key(event_type), bool(source)
        if source:
            return _source_index_key(source), False
        return TIMELINE_KEY, bool(event_type or source or user)


def get_event_repository(redis_client: redis.Redis = Depends(get_redis)) -> EventRepository:
    return EventRepository(redis_client)


def _event_key(event_id: int) -> str:
    return f"{EVENT_KEY_PREFIX}{event_id}"


def _type_index_key(value: str) -> str:
    return f"{TYPE_INDEX_PREFIX}{quote_plus(value)}"


def _source_index_key(value: str) -> str:
    return f"{SOURCE_INDEX_PREFIX}{quote_plus(value)}"


def _user_index_key(value: str) -> str:
    return f"{USER_INDEX_PREFIX}{quote_plus(value)}"


def _score(value: datetime) -> float:
    return value.replace(tzinfo=timezone.utc).timestamp()


def _deserialize_event(event_id: int, data: dict) -> EventRecord:
    user_is_null = data.get("user_is_null") == "1"
    user_value = data.get("user", "")
    user = None if user_is_null else user_value
    when_raw = data.get("when", "")
    payload_raw = data.get("payload", "{}")
    when = parse_datetime_string(when_raw)
    payload = json.loads(payload_raw)
    return EventRecord(
        id=event_id,
        when=when,
        source=data.get("source", ""),
        type=data.get("type", ""),
        payload=payload,
        user=user,
    )
