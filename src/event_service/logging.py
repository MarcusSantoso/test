from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import Request

from src.shared.redis_client import get_redis

from .repository import EventRepository
from .schemas import EventCreateSchema

logger = logging.getLogger("uvicorn.error")


class RequestEventLogger:
    """
    Helper responsible for emitting request metadata into the event stream.
    """

    async def log_request(self, request: Request, response_status: int) -> None:
        try:
            await self._write_event(request, response_status)
        except Exception:
            logger.exception("Failed to log request event", extra={"path": str(request.url)})

    async def _write_event(self, request: Request, response_status: int) -> None:
        if not _should_log_request(request):
            return
        try:
            redis_client = get_redis()
        except Exception:
            # If Redis is not configured or unavailable, skip event logging
            logger.exception("Redis unavailable for request-event logging; skipping")
            return
        repo = EventRepository(redis_client)
        when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        payload: dict[str, Any] = {
            "method": request.method,
            "client": request.client.host if request.client else None,
            "status": response_status,
        }
        user = getattr(request.state, "user_id", None)
        event = EventCreateSchema(
            when=when,
            source=str(request.url),
            type=_event_type_for(request),
            payload=payload,
            user=user,
        )
        await repo.create(event)


request_event_logger = RequestEventLogger()


IGNORED_PREFIXES = (
    "/admin/_nicegui/",
    "/_nicegui/",
    "/static/",
    "/docs",
    "/redoc",
    "/openapi.json",
)
IGNORED_SUFFIXES = (
    ".js",
    ".css",
    ".ico",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".map",
    ".gif",
    ".woff",
    ".woff2",
)


def _should_log_request(request: Request) -> bool:
    path = request.url.path
    if any(path.startswith(prefix) for prefix in IGNORED_PREFIXES):
        return False
    if any(path.endswith(suffix) for suffix in IGNORED_SUFFIXES):
        return False
    return True


def _event_type_for(request: Request) -> str:
    return f"http {request.method.upper()} {request.url.path}"
