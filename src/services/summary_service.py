from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.services.ai_summarization_engine import (
    AISummarizationEngine,
    SummarizationOptions,
)
from src.user_service.models import AISummary, Professor, Review


SUMMARY_PROMPT = (
    "You analyze collections of professor reviews. "
    "Produce a balanced summary as JSON with keys 'pros', 'cons', and 'neutral'. "
    "Each value must be an array of short bullet strings (<=25 words) summarizing recurring themes. "
    "Only include statements supported by the reviews. When a category has no insights return an empty array. "
    "Respond with STRICT JSON only, no markdown or prose."
)

MAX_SUMMARY_WORDS = 250
MAX_PROMPT_CHARS = 12_000
AUTO_REFRESH_REVIEW_DELTA = 3
AUTO_REFRESH_WINDOW = timedelta(days=7)


class SummaryService:
    """Coordinates review aggregation, AI summarization, and persistence."""

    def __init__(
        self,
        session: Session,
        engine: AISummarizationEngine,
        *,
        review_limit: int | None = None,
        max_prompt_chars: int = MAX_PROMPT_CHARS,
    ) -> None:
        self.session = session
        self.engine = engine
        self.review_limit = review_limit
        self.max_prompt_chars = max_prompt_chars

    async def fetch_summary(
        self,
        prof_id: int,
        *,
        auto_refresh: bool = True,
        force_refresh: bool = False,
    ) -> AISummary:
        professor = self.session.get(Professor, prof_id)
        if not professor:
            raise LookupError("Professor not found")

        summary = self._get_summary_row(prof_id)
        review_count = self._get_review_count(prof_id)
        if review_count == 0:
            raise ValueError("Professor has no reviews to summarize")

        needs_refresh = force_refresh or summary is None
        if auto_refresh and not needs_refresh:
            needs_refresh = self._should_refresh(summary, review_count)

        if needs_refresh:
            reviews = self._load_recent_reviews(prof_id)
            summary = await self._generate_summary(
                prof_id, summary, reviews, review_count
            )

        return summary

    def _get_review_count(self, prof_id: int) -> int:
        stmt = select(func.count(Review.id)).where(Review.prof_id == prof_id)
        return int(self.session.scalar(stmt) or 0)

    def _load_recent_reviews(self, prof_id: int) -> Sequence[Review]:
        stmt = (
            select(Review)
            .where(Review.prof_id == prof_id)
            .order_by(Review.timestamp.desc().nullslast(), Review.id.desc())
        )
        if self.review_limit:
            stmt = stmt.limit(self.review_limit)
        return list(self.session.scalars(stmt))

    def _get_summary_row(self, prof_id: int) -> AISummary | None:
        stmt = select(AISummary).where(AISummary.prof_id == prof_id)
        return self.session.scalar(stmt)

    def _should_refresh(self, summary: AISummary, review_count: int) -> bool:
        updated_at = summary.updated_at
        if updated_at is None:
            return True
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if now - updated_at >= AUTO_REFRESH_WINDOW:
            return True
        snapshot = summary.review_count_snapshot or 0
        return (review_count - snapshot) >= AUTO_REFRESH_REVIEW_DELTA

    async def _generate_summary(
        self,
        prof_id: int,
        summary_row: AISummary | None,
        reviews: Sequence[Review],
        total_review_count: int,
    ) -> AISummary:
        formatted = self._format_reviews(reviews)
        if not formatted:
            raise ValueError("No usable review text to summarize")

        summary_text, _raw = await self.engine.summarize_with_raw(
            formatted,
            options=SummarizationOptions(
                instructions=SUMMARY_PROMPT,
                max_words=MAX_SUMMARY_WORDS,
            ),
        )
        parsed = self._parse_summary(summary_text)

        summary_model = summary_row or AISummary(prof_id=prof_id)
        summary_model.pros = parsed["pros"]
        summary_model.cons = parsed["cons"]
        summary_model.neutral = parsed["neutral"]
        summary_model.updated_at = datetime.now(timezone.utc)
        summary_model.review_count_snapshot = total_review_count

        self.session.add(summary_model)
        self.session.commit()
        self.session.refresh(summary_model)
        return summary_model

    def _format_reviews(self, reviews: Sequence[Review]) -> str:
        chunks: list[str] = []
        for idx, review in enumerate(reviews, start=1):
            text = (review.text or "").strip()
            if not text:
                continue

            meta_parts: list[str] = []
            if review.source:
                meta_parts.append(f"source={review.source}")
            if review.rating is not None:
                meta_parts.append(f"rating={review.rating}")
            if review.timestamp:
                meta_parts.append(f"timestamp={review.timestamp.isoformat()}")

            header = f"Review {idx}"
            if meta_parts:
                header += f" ({', '.join(meta_parts)})"
            chunks.append(f"{header}:\n{text}")

        payload = "\n\n".join(chunks).strip()
        if len(payload) > self.max_prompt_chars:
            payload = payload[: self.max_prompt_chars]
        return payload

    def _parse_summary(self, summary_text: str) -> dict[str, list[str]]:
        try:
            data = json.loads(summary_text)
        except json.JSONDecodeError:
            data = self._parse_heuristic(summary_text)

        return {
            "pros": self._coerce_string_list(data.get("pros")),
            "cons": self._coerce_string_list(data.get("cons")),
            "neutral": self._coerce_string_list(data.get("neutral")),
        }

    def _parse_heuristic(self, text: str) -> dict[str, list[str]]:
        # Basic fallback when the model fails to provide JSON.
        sections = {"pros": [], "cons": [], "neutral": []}
        current = None
        for line in text.splitlines():
            lowered = line.lower().strip(": ").strip()
            if lowered in sections:
                current = lowered
                continue
            if not line.strip() or current is None:
                continue
            sections[current].append(line.strip("- •").strip())
        return sections

    def _coerce_string_list(self, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, (list, tuple, set)):
            out: list[str] = []
            for item in value:
                if isinstance(item, str):
                    cleaned = item.strip()
                    if cleaned:
                        out.append(cleaned)
            return out
        return []
