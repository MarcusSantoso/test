from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.user_service.models.user import Base
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .review import Review
    from .ai_summary import AISummary


class Professor(Base):
    __tablename__ = "professors"
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    department: Mapped[str | None] = mapped_column(String, nullable=True)
    rmp_url: Mapped[str | None] = mapped_column(String, nullable=True)
    course_codes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # relationships
    reviews: Mapped[list["Review"]] = relationship(
        "Review", back_populates="professor", cascade="all, delete-orphan"
    )
    ai_summary: Mapped["AISummary"] = relationship(
        "AISummary", back_populates="professor", uselist=False, cascade="all, delete-orphan"
    )
