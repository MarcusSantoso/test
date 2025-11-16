from __future__ import annotations

from fastapi import Depends
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from src.shared.database import get_db
from src.user_service.models.ai_summary_history import AISummaryHistory


class AISummaryHistoryRepository:
    def __init__(self, session: Session):
        self.session = session

    async def record(
        self,
        *,
        source_text: str,
        summary_text: str,
        context: str | None = None,
        raw_response: str | None = None,
    ) -> AISummaryHistory:
        entry = AISummaryHistory(
            source_text=source_text,
            summary_text=summary_text,
            context=context,
            raw_response=raw_response,
        )
        self.session.add(entry)
        self.session.commit()
        self.session.refresh(entry)
        return entry

    async def list_recent(self, limit: int = 10) -> list[AISummaryHistory]:
        stmt = (
            select(AISummaryHistory)
            .order_by(AISummaryHistory.created_at.desc(), AISummaryHistory.id.desc())
            .limit(limit)
        )
        result = self.session.scalars(stmt)
        return list(result)

    async def delete_entry(self, entry_id: int) -> None:
        stmt = delete(AISummaryHistory).where(AISummaryHistory.id == entry_id)
        self.session.execute(stmt)
        self.session.commit()

    async def clear(self) -> None:
        self.session.execute(delete(AISummaryHistory))
        self.session.commit()


def get_ai_summary_history_repository(
    db: Session = Depends(get_db),
) -> AISummaryHistoryRepository:
    return AISummaryHistoryRepository(db)
