import json
import logging
import math
import os
import threading
from typing import List, Optional

from sqlalchemy.orm import Session

from src.user_service.models import Professor, Review
from src.shared.database import get_db

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - defensive fallback
    OpenAI = None


logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"


# ---------------------------------------------------------------------------
# Helpers: OpenAI client + cosine similarity (no numpy dependency)
# ---------------------------------------------------------------------------


def _get_openai_client() -> "OpenAI":
    """
    Lazily construct an OpenAI client.

    We intentionally DO NOT fail at import time if OPENAI_API_KEY is missing,
    because the test suite imports the app without needing semantic search.
    Instead, we only require the key when an embedding is actually requested.
    """
    if OpenAI is None:
        raise RuntimeError("OpenAI SDK is not installed")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is required for semantic search")

    return OpenAI(api_key=api_key)


def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """
    Pure Python cosine similarity implementation (no numpy).

    Returns 0.0 if vectors are empty, mismatched, or have zero norm.
    """
    if not v1 or not v2:
        return 0.0
    if len(v1) != len(v2):
        return 0.0

    dot = 0.0
    norm1 = 0.0
    norm2 = 0.0
    for a, b in zip(v1, v2):
        dot += a * b
        norm1 += a * a
        norm2 += b * b

    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0

    return dot / (math.sqrt(norm1) * math.sqrt(norm2))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_openai_embedding(text_input: str) -> List[float]:
    """
    Get an embedding vector for the given text using OpenAI.
    """
    text_input = (text_input or "").strip()
    if not text_input:
        return []

    client = _get_openai_client()
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=text_input)
    embedding = resp.data[0].embedding
    # Ensure we always return a plain list of floats (JSON serialisable)
    return list(embedding)


def _aggregate_professor_reviews(session: Session, professor_id: int) -> Optional[str]:
    """
    Aggregate all reviews for a professor into a single text block.
    """
    reviews = (
        session.query(Review)
        .filter(Review.prof_id == professor_id)
        .order_by(Review.id.asc())
        .all()
    )
    if not reviews:
        return None

    parts: List[str] = []
    for r in reviews:
        text = (r.text or "").strip()
        if not text:
            continue
        if r.rating is not None:
            parts.append(f"Rating {r.rating}: {text}")
        else:
            parts.append(text)

    if not parts:
        return None

    return "\n\n".join(parts)


def precompute_and_store_all_embeddings(session: Session, batch_size: int = 200) -> None:
    """
    Compute embeddings for all professors that have at least one review.

    This is intended for one-off / admin use. It does not run automatically.
    """
    logger.info("Starting precompute_and_store_all_embeddings (batch_size=%s)", batch_size)

    professors = session.query(Professor).order_by(Professor.id.asc()).all()
    count_updated = 0

    for prof in professors:
        combined = _aggregate_professor_reviews(session, prof.id)
        if not combined:
            continue

        try:
            emb = get_openai_embedding(combined)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Failed to embed professor id=%s: %s", prof.id, exc)
            continue

        prof.embedding = emb
        session.add(prof)
        count_updated += 1

        if count_updated % batch_size == 0:
            session.commit()
            logger.info("Committed %s professor embeddings so far", count_updated)

    session.commit()
    logger.info("Finished precomputing embeddings. Updated=%s", count_updated)


def recompute_professor_embedding(session: Session, professor_id: int) -> None:
    """
    Recompute and store the embedding for a single professor based on their reviews.
    """
    prof = session.query(Professor).filter(Professor.id == professor_id).first()
    if not prof:
        logger.warning("recompute_professor_embedding: professor %s not found", professor_id)
        return

    combined = _aggregate_professor_reviews(session, professor_id)
    if not combined:
        logger.info("Professor %s has no reviews to embed", professor_id)
        prof.embedding = None
        session.add(prof)
        session.commit()
        return

    emb = get_openai_embedding(combined)
    prof.embedding = emb
    session.add(prof)
    session.commit()
    logger.info("Updated embedding for professor id=%s", professor_id)


def enqueue_recompute_professor_embedding(professor_id: int) -> None:
    """
    Best-effort background task that recomputes a professor's embedding.

    This opens a fresh DB session via get_db() inside a daemon thread so that
    we do not block the main request (e.g., scraper).
    """

    def _worker() -> None:
        db_gen = get_db()
        session: Session = next(db_gen)
        try:
            recompute_professor_embedding(session, professor_id)
        finally:
            session.close()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def search_professors(
    session: Session,
    query: str,
    threshold: float = 0.7,
    limit: int = 20,
    department: Optional[str] = None,
    course_level: Optional[str] = None,  # currently unused, kept for future extension
) -> List[dict]:
    """
    Semantic search for professors.

    - `query` is natural language (e.g., "easy grader", "heavy workload").
    - Only professors with a non-null embedding are considered.
    - Results are filtered by cosine similarity >= `threshold` and sorted desc.
    """
    query = (query or "").strip()
    if not query:
        return []

    try:
        query_vec = get_openai_embedding(query)
    except Exception as exc:
        logger.exception("Failed to embed search query: %s", exc)
        return []

    if not query_vec:
        return []

    q = session.query(Professor).filter(Professor.embedding != None)  # noqa: E711
    if department:
        q = q.filter(Professor.department == department)

    professors = q.all()
    results: List[dict] = []

    for prof in professors:
        raw = prof.embedding
        if raw is None:
            continue

        # Support both JSON string and native list storage.
        if isinstance(raw, str):
            try:
                emb_vec = json.loads(raw)
            except json.JSONDecodeError:
                continue
        else:
            emb_vec = raw

        if not isinstance(emb_vec, list):
            continue

        try:
            emb_vec_floats = [float(x) for x in emb_vec]
        except (TypeError, ValueError):
            continue

        sim = _cosine_similarity(query_vec, emb_vec_floats)
        if sim >= threshold:
            results.append(
                {
                    "id": prof.id,
                    "name": prof.name,
                    "department": prof.department,
                    "similarity": sim,
                }
            )

    results.sort(key=lambda r: r["similarity"], reverse=True)
    if limit and limit > 0:
        results = results[:limit]

    return results
