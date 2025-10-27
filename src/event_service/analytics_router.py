from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from .analytics import EventAnalyticsService
from .repository import EventRepository, get_event_repository
from .time_utils import utc_now_naive

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date format, expected YYYY-MM-DD",
        ) from exc


def _validate_window(target_day: date):
    today = utc_now_naive().date()
    if target_day > today:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Date cannot be in the future",
        )
    if (today - target_day).days > 365:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Date must be within the past 365 days",
        )


@router.get("/")
async def read_analytics(
    on: str | None = None,
    since: str | None = None,
    repo: EventRepository = Depends(get_event_repository),
):
    if on and since:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Specify either 'on' or 'since', not both",
        )

    service = EventAnalyticsService(repo)

    if on:
        day = _parse_date(on)
        _validate_window(day)
        snapshot = await service.on(day)
        return snapshot.to_dict()

    if since:
        start_day = _parse_date(since)
        _validate_window(start_day)
        snapshot = await service.since(start_day)
        return snapshot.to_dict()

    snapshot = await service.today()
    return snapshot.to_dict()
