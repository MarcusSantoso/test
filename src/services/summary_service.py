from __future__ import annotations

import json
import ast
from collections.abc import Callable
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
    "You analyze collections of professor reviews. Produce a short, lively, human-friendly paragraph summary, and also provide a machine-readable JSON object. "
    "Return ONLY valid JSON (no markdown or extra text). The JSON object must contain the keys: 'text_summary', 'pros', 'cons', and 'neutral'. "
    "- 'text_summary': a 1-3 sentence lively, engaging paragraph (use vivid but professional language). Keep under 50 words.\n"
    "- 'pros', 'cons', 'neutral': each an array of short bullet strings (<=25 words) summarizing recurring themes from the reviews. "
    "Only include statements supported by the reviews. For empty categories, return an empty array."
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
        engine: AISummarizationEngine | Callable[[], AISummarizationEngine],
        *,
        review_limit: int | None = None,
        max_prompt_chars: int = MAX_PROMPT_CHARS,
    ) -> None:
        self.session = session
        self._engine_instance: AISummarizationEngine | None = None
        self._engine_factory: Callable[[], AISummarizationEngine] | None = None
        if callable(engine):
            self._engine_factory = engine
        else:
            self._engine_instance = engine
        # Preserve backwards compatibility for any callers that reference
        # `self.engine` directly by mirroring the resolved instance.
        self.engine: AISummarizationEngine | None = self._engine_instance
        self.review_limit = review_limit
        self.max_prompt_chars = max_prompt_chars

    async def fetch_summary(
        self,
        prof_id: int,
        *,
        auto_refresh: bool = True,
        force_refresh: bool = False,
        persist: bool = True,
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

        # If a summary row exists but contains no structured bullets, treat
        # it as stale/missing and schedule a refresh when auto_refresh is
        # enabled. This covers cases where an earlier summarization run
        # produced empty arrays (e.g. model hiccup) but we still want the
        # UI to show a lively paragraph without requiring a manual button
        # click.
        if (
            auto_refresh
            and not force_refresh
            and summary is not None
            and not needs_refresh
        ):
            has_bullets = bool((summary.pros and any(x.strip() for x in (summary.pros or []))) or (summary.cons and any(x.strip() for x in (summary.cons or []))) or (summary.neutral and any(x.strip() for x in (summary.neutral or []))))
            if not has_bullets:
                needs_refresh = True

        if needs_refresh:
            reviews = self._load_recent_reviews(prof_id)
            summary = await self._generate_summary(
                prof_id, summary, reviews, review_count, persist=persist
            )

        # We deliberately avoid making additional AI calls here to synthesize
        # a human-friendly paragraph on read; doing so would cause one-off
        # model calls on every GET and increase cost and test flakiness. The
        # API serialization layer (`_serialize_professor_summary`) will
        # synthesize a compact fallback from stored bullets when needed, and
        # explicit generation should be done via the refresh endpoint.

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
        persist: bool = True,
    ) -> AISummary:
        formatted = self._format_reviews(reviews)
        if not formatted:
            raise ValueError("No usable review text to summarize")

        engine = self._get_engine()
        summary_text, _raw = await engine.summarize_with_raw(
            formatted,
            options=SummarizationOptions(
                instructions=SUMMARY_PROMPT,
                max_words=MAX_SUMMARY_WORDS,
            ),
        )

        # Expecting a JSON object containing text_summary, pros, cons, neutral.
        try:
            data = json.loads(summary_text)
        except json.JSONDecodeError:
            # Try to recover malformed JSON by extracting a top-level JSON
            # substring (handles cases where the model wrapped the JSON with
            # extra commentary) or by falling back to Python literal_eval for
            # single-quoted dicts. If all parsing attempts fail, use the
            # heuristic parser.
            data = None
            # Attempt to extract a balanced JSON object substring.
            json_sub = self._extract_json_substring(summary_text)
            if json_sub:
                try:
                    data = json.loads(json_sub)
                except json.JSONDecodeError:
                    try:
                        data = ast.literal_eval(json_sub)
                    except Exception:
                        data = None
            if data is None:
                try:
                    data = ast.literal_eval(summary_text)
                except Exception:
                    data = self._parse_heuristic(summary_text)
            # Ensure we have a dict-like structure
            if not isinstance(data, dict):
                data = {}
            # Ensure there's always a text_summary key
            data.setdefault("text_summary", "")

        pros = self._coerce_string_list(data.get("pros"))
        cons = self._coerce_string_list(data.get("cons"))
        neutral = self._coerce_string_list(data.get("neutral"))

        # If persistence is requested, update or create the DB row. Otherwise
        # construct an in-memory AISummary object and return it without
        # committing so generated summaries are ephemeral.
        if persist:
            summary_model = summary_row or AISummary(prof_id=prof_id)
            summary_model.pros = pros
            summary_model.cons = cons
            summary_model.neutral = neutral
            summary_model.updated_at = datetime.now(timezone.utc)
            summary_model.review_count_snapshot = total_review_count

            # Persist structured arrays only (avoid DB migrations for text_summary).
            self.session.add(summary_model)
            self.session.commit()
            self.session.refresh(summary_model)

            ts = data.get("text_summary") or data.get("summary") or ""
            text_summary = ts.strip() if isinstance(ts, str) else ""
            setattr(summary_model, "_text_summary_cached", text_summary)
            return summary_model
        else:
            # Build a transient AISummary-like object (not attached to session)
            summary_model = AISummary(prof_id=prof_id)
            summary_model.pros = pros
            summary_model.cons = cons
            summary_model.neutral = neutral
            summary_model.updated_at = datetime.now(timezone.utc)
            summary_model.review_count_snapshot = total_review_count
            ts = data.get("text_summary") or data.get("summary") or ""
            text_summary = ts.strip() if isinstance(ts, str) else ""
            setattr(summary_model, "_text_summary_cached", text_summary)
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

    def _extract_json_substring(self, text: str) -> str | None:
        """Return the first balanced JSON object substring found in text, or None.

        This performs a simple brace-matching scan to cope with extra
        commentary surrounding a JSON object produced by the model.
        """
        if not text:
            return None
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

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

    def _get_engine(self) -> AISummarizationEngine:
        if self._engine_instance is None:
            if not self._engine_factory:
                raise RuntimeError("Summarization engine is not configured")
            self._engine_instance = self._engine_factory()
            self.engine = self._engine_instance
        return self._engine_instance
