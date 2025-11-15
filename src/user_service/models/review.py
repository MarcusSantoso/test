from __future__ import annotations

from datetime import datetime
from sqlalchemy import Integer, ForeignKey, Text, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.user_service.models.user import Base


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prof_id: Mapped[int] = mapped_column(ForeignKey("professors.id", ondelete="CASCADE"), nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)

    professor = relationship("Professor", back_populates="reviews")
