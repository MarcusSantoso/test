from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Any

class EventCreate(BaseModel):
    when: datetime
    source: str
    type: str
    payload: dict
    user: Optional[str] = None

class EventRead(EventCreate):
    id: int

    class Config:
        orm_mode = True
