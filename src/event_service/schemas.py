from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field

from .time_utils import format_datetime


class EventLike(Protocol):
    id: int
    when: datetime
    source: str
    type: str
    payload: dict[str, Any]
    user: str | None


class EventCreateSchema(BaseModel):
    when: str = Field(..., description="Datetime string in ISO 8601 format")
    source: str
    type: str
    payload: dict[str, Any]
    user: str | None = Field(default=None, description="Optional user identifier")


class EventSchema(BaseModel):
    id: int
    when: str
    source: str
    type: str
    payload: dict[str, Any]
    user: str | None = None

    @classmethod
    def from_db_model(cls, event: EventLike) -> "EventSchema":
        return cls(
            id=event.id,
            when=format_datetime(event.when),
            source=event.source,
            type=event.type,
            payload=event.payload,
            user=event.user,
        )
