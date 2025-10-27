from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, Index
from sqlalchemy.orm import Mapped, mapped_column

from src.user_service.models.user import Base


class Event(Base):
    """Analytics event emitted by any of the client properties."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    when: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String, nullable=False, index=True)
    type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    user: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    __table_args__ = (
        Index("ix_events_type_when", "type", "when"),
        Index("ix_events_source_when", "source", "when"),
    )
