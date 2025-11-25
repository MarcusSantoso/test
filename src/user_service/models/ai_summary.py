from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Integer, ForeignKey, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.user_service.models.user import Base

if TYPE_CHECKING:
    from .professor import Professor


class AISummary(Base):
    __tablename__ = "ai_summaries"
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prof_id: Mapped[int] = mapped_column(ForeignKey("professors.id", ondelete="CASCADE"), nullable=False, unique=True)
    pros: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    cons: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    neutral: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_count_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)

    professor: Mapped["Professor"] = relationship(
        "Professor", back_populates="ai_summary"
    )
