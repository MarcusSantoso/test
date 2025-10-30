from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .repository import EventRepository, get_event_repository
from .schemas import EventCreateSchema, EventSchema
from .time_utils import parse_datetime_string

router = APIRouter(prefix="/events", tags=["events"])


#iankatzeff
@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_event(
    payload: EventCreateSchema,
    repo: EventRepository = Depends(get_event_repository),
):
    event = await repo.create(payload)
    return {"event": EventSchema.from_db_model(event)}


#iankatzeff
@router.get("/")
async def list_events(
    event_type: str | None = Query(default=None, alias="type"),
    source: str | None = None,
    before: str | None = None,
    after: str | None = None,
    user: str | None = None,
    repo: EventRepository = Depends(get_event_repository),
):
    try:
        before_dt = parse_datetime_string(before) if before else None
        after_dt = parse_datetime_string(after) if after else None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    events = await repo.query(
        event_type=event_type,
        source=source,
        before=before_dt,
        after=after_dt,
        user=user,
    )
    return {"events": [EventSchema.from_db_model(event) for event in events]}

