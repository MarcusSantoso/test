from __future__ import annotations

from datetime import datetime
from sqlalchemy import Integer, ForeignKey, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.user_service.models.user import Base


class AISummary(Base):
    __tablename__ = "ai_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prof_id: Mapped[int] = mapped_column(ForeignKey("professors.id", ondelete="CASCADE"), nullable=False, unique=True)
    pros: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    cons: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    neutral: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    professor = relationship("Professor", back_populates="ai_summary")
