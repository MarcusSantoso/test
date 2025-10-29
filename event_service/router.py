from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional, List

from .schema import EventCreate, EventRead
from .repository import EventRepository
from shared.database import get_db

router = APIRouter(prefix="/v2/events", tags=["Events"])

@router.post("/", response_model=EventRead)
def create_event(event: EventCreate, db: Session = Depends(get_db)):
    repo = EventRepository(db)
    created = repo.create_event(event.dict())
    return created

@router.get("/", response_model=List[EventRead])
def get_events(
    type: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    before: Optional[datetime] = Query(None),
    after: Optional[datetime] = Query(None),
    user: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    repo = EventRepository(db)
    events = repo.query_events(type, source, before, after, user)
    return events
