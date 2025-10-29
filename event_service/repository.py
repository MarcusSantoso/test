from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional, List
from .models import Event

class EventRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_event(self, event_data: dict) -> Event:
        event = Event(**event_data)
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def query_events(
        self,
        type: Optional[str] = None,
        source: Optional[str] = None,
        before: Optional[datetime] = None,
        after: Optional[datetime] = None,
        user: Optional[str] = None,
    ) -> List[Event]:
        query = self.db.query(Event)

        if type:
            query = query.filter(Event.type == type)
        if source:
            query = query.filter(Event.source == source)
        if before:
            query = query.filter(Event.when <= before)
        if after:
            query = query.filter(Event.when >= after)
        if user:
            query = query.filter(Event.user == user)

        return query.order_by(Event.when.desc()).all()
