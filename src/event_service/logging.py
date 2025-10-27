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
        repo = EventRepository(get_redis())
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
            type="api-request",
            payload=payload,
            user=user,
        )
        await repo.create(event)


request_event_logger = RequestEventLogger()
