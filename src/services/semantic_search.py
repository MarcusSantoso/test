import json
import os
import logging
from typing import List, Optional, Dict, Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY environment variable is required for semantic search")

# Try to support both the old and new openai SDKs:
# - New: `from openai import OpenAI` -> client = OpenAI(); client.embeddings.create(...)
# - Old: `import openai` -> openai.Embedding.create(...)
_USE_NEW_OPENAI = False
try:
    from openai import OpenAI  # type: ignore
    _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    _USE_NEW_OPENAI = True
except Exception:
    try:
        import openai as _openai
        _openai.api_key = OPENAI_API_KEY
        _openai_client = _openai
        _USE_NEW_OPENAI = False
    except Exception as exc:
        raise RuntimeError("Failed to import OpenAI SDK: " + str(exc))

EMBEDDING_MODEL = "text-embedding-3-small"


def get_openai_embedding(text_input: str) -> List[float]:
    """Return embedding for given text using OpenAI embeddings API."""
    if not text_input:
        return []

    # keep input reasonably sized
    text_input = text_input.strip()
    if len(text_input) > 30000:
        text_input = text_input[-30000:]

    if _USE_NEW_OPENAI:
        # new SDK style
        resp = _openai_client.embeddings.create(model=EMBEDDING_MODEL, input=text_input)
        try:
            emb = resp.data[0].embedding
        except Exception:
            emb = resp["data"][0]["embedding"]
    else:
        resp = _openai_client.Embedding.create(model=EMBEDDING_MODEL, input=text_input)
        emb = resp["data"][0]["embedding"]

    return list(emb)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 or b.size == 0:
        return -1.0
    an = a.astype(np.float32)
    bn = b.astype(np.float32)
    denom = np.linalg.norm(an) * np.linalg.norm(bn)
    if denom == 0:
        return -1.0
    return float(np.dot(an, bn) / denom)


def _aggregate_reviews_for_professors(session: Session, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """Return list of dicts {id, reviews_text} by aggregating reviews per professor.

    Uses `string_agg` over `reviews.text` and orders reviews by `timestamp` if available.
    """
    sql = text(
        """
        SELECT p.id as id,
               COALESCE(
                   string_agg(
                       r.text,
                       ' . '
                       ORDER BY r.timestamp NULLS LAST, r.id
                   ),
                   ''
               ) AS reviews_text
        FROM professors p
        LEFT JOIN reviews r ON r.prof_id = p.id
        GROUP BY p.id
        ORDER BY p.id
        LIMIT :limit OFFSET :offset
        """
    )
    res = session.execute(sql, {"limit": limit, "offset": offset}).mappings().all()
    return [dict(row) for row in res]


def precompute_and_store_all_embeddings(session: Session, batch_size: int = 200) -> None:
    """Compute embeddings for all professors by aggregating their reviews and store in the DB.

    Run this as a one-off or background job. WARNING: this calls OpenAI for each professor and
    will incur API usage/costs.
    """
    offset = 0
    while True:
        rows = _aggregate_reviews_for_professors(session, limit=batch_size, offset=offset)
        if not rows:
            break
        for row in rows:
            prof_id = row["id"]
            reviews_text = row.get("reviews_text") or ""
            if not reviews_text:
                session.execute(text("UPDATE professors SET embedding = NULL WHERE id = :id"), {"id": prof_id})
                continue
            emb = get_openai_embedding(reviews_text)
            session.execute(
                text("UPDATE professors SET embedding = CAST(:emb AS jsonb) WHERE id = :id"),
                {"emb": json.dumps(emb), "id": prof_id},
            )

        session.commit()
        offset += len(rows)


def recompute_professor_embedding(session: Session, professor_id: int) -> None:
    """Recompute embedding for a single professor by aggregating their reviews and overwriting embedding.

    Call this from the code path that inserts a new review (enqueue as background job if latency matters).
    """
    sql = text(
        """
        SELECT COALESCE(
                   string_agg(
                       r.text,
                       ' . '
                       ORDER BY r.timestamp NULLS LAST, r.id
                   ),
                   ''
               ) AS reviews_text
        FROM reviews r
        WHERE r.prof_id = :pid
        """
    )
    row = session.execute(sql, {"pid": professor_id}).mappings().first()
    reviews_text = (row and row.get("reviews_text")) or ""
    if not reviews_text:
        session.execute(text("UPDATE professors SET embedding = NULL WHERE id = :id"), {"id": professor_id})
        session.commit()
        return
        emb = get_openai_embedding(reviews_text)
        session.execute(
        text("UPDATE professors SET embedding = CAST(:emb AS jsonb) WHERE id = :id"),
        {"emb": json.dumps(emb), "id": professor_id},
    )
    session.commit()




def search_professors(
    session: Session,
    query: str,
    threshold: float = 0.7,
    limit: int = 20,
    department: Optional[str] = None,
    course_level: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search professors by semantic similarity to `query`.

    Returns list of dicts with keys: id, name, department (if present), similarity.
    Professors without stored embeddings are ignored.
    """
    if not query:
        return []

    q_emb = np.array(get_openai_embedding(query), dtype=np.float32)
    # Build SQL with optional department filter. Note: course_level not present in Professor model.
    where_clauses = ["embedding IS NOT NULL"]
    params: Dict[str, Any] = {}
    if department:
        where_clauses.append("department = :department")
        params["department"] = department
    where_sql = " AND ".join(where_clauses)
    sql = text(f"SELECT id, name, department, embedding FROM professors WHERE {where_sql}")
    res = session.execute(sql, params).mappings().all()

    candidates: List[Dict[str, Any]] = []
    for row in res:
        emb = row.get("embedding")
        if not emb:
            continue
        emb_arr = np.array(emb, dtype=np.float32)
        sim = _cosine_similarity(q_emb, emb_arr)
        if sim >= threshold:
            r = {"id": row["id"], "name": row.get("name"), "department": row.get("department"), "similarity": float(sim)}
            candidates.append(r)

    candidates.sort(key=lambda x: x["similarity"], reverse=True)
    return candidates[:limit]


# --- enqueue helper (non-blocking) ---
import threading
from src.shared.database import get_db

def enqueue_recompute_professor_embedding(professor_id: int) -> None:
    """
    Start a daemon thread to recompute the professor's embedding.
    The worker creates its own DB session using `get_db()` so this call
    is non-blocking from the caller's perspective.
    """
    def _job():
        gen = None
        try:
            gen = get_db()
            session = next(gen)
            try:
                recompute_professor_embedding(session, professor_id)
            except Exception:
                logger.exception("recompute_professor_embedding failed for professor id=%s", professor_id)
        except Exception:
            logger.exception("Failed to start DB session for recompute_professor_embedding (professor id=%s)", professor_id)
        finally:
            try:
                if gen is not None:
                    gen.close()
            except Exception:
                pass

    t = threading.Thread(target=_job, daemon=True)
    t.start()
# === Patch: enforce safe max length for embedding inputs ===
# Some professors can accumulate very long aggregated review text
# which may exceed the model's 8192-token context limit.
# We re-define get_openai_embedding with a simple char-based truncation.
from typing import List
import os

try:
    from openai import OpenAI  # new SDK
except ImportError:  # fallback
    import openai as OpenAI  # type: ignore[assignment]


def get_openai_embedding(text_input: str) -> List[float]:
    """
    Get an embedding for the given text, with a safety truncation so that
    we don't exceed the model's maximum context length.

    This definition intentionally overrides any earlier get_openai_embedding
    in this module.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is required for semantic search")

    # Approximate: ~4 characters per token. To stay safely under 8192 tokens,
    # we cap around 28000 characters.
    max_chars = 28000
    if len(text_input) > max_chars:
        text_input = text_input[:max_chars]

    # Use new-style OpenAI client if available, otherwise fall back.
    try:
        client = OpenAI(api_key=api_key)  # type: ignore[call-arg]
        resp = client.embeddings.create(
            model="text-embedding-3-small",
            input=text_input,
        )
        return resp.data[0].embedding  # type: ignore[index]
    except TypeError:
        # Fallback for older "openai" import style
        resp = OpenAI.Embedding.create(  # type: ignore[attr-defined]
            model="text-embedding-3-small",
            input=text_input,
            api_key=api_key,
        )
        return resp["data"][0]["embedding"]  # type: ignore[index]


# === Patch 2: chunked embedding to stay under context limit ===
# Some professors have very long aggregated review text. To avoid exceeding
# the model context window, we split the text into chunks and average
# the embeddings for each chunk.
from typing import List
import os

try:
    from openai import OpenAI as _OpenAIClient  # new SDK
except ImportError:  # fallback
    import openai as _OpenAIClient  # type: ignore[assignment]


def get_openai_embedding(text_input: str) -> List[float]:
    """
    Get an embedding for the given text, safely handling very long inputs
    by splitting into smaller chunks and averaging the embeddings.

    This definition intentionally overrides any earlier get_openai_embedding
    in this module.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is required for semantic search")

    # Helper to embed a single (reasonably short) string
    def _embed_once(chunk: str) -> List[float]:
        # We keep each chunk quite short in characters so we stay well under
        # the 8192-token limit even in worst-case tokenization.
        if not chunk:
            return []

        try:
            client = _OpenAIClient(api_key=api_key)  # type: ignore[call-arg]
            resp = client.embeddings.create(
                model="text-embedding-3-small",
                input=chunk,
            )
            return resp.data[0].embedding  # type: ignore[index]
        except TypeError:
            # Fallback for older "openai" import style
            resp = _OpenAIClient.Embedding.create(  # type: ignore[attr-defined]
                model="text-embedding-3-small",
                input=chunk,
                api_key=api_key,
            )
            return resp["data"][0]["embedding"]  # type: ignore[index]

    # Split very long text into small chunks (by characters).
    # 4000 chars per chunk is very conservative vs 8192 tokens.
    max_chunk_chars = 4000
    text = text_input or ""
    chunks: list[str] = [
        text[i : i + max_chunk_chars]
        for i in range(0, len(text), max_chunk_chars)
    ] or [""]

    # Compute embeddings for each chunk and average them
    embeddings: list[List[float]] = []
    for ch in chunks:
        vec = _embed_once(ch)
        if vec:
            embeddings.append(vec)

    if not embeddings:
        # Should be rare; fall back to a single empty embedding call
        return _embed_once("")

    # Average element-wise
    dim = len(embeddings[0])
    summed = [0.0] * dim
    for vec in embeddings:
        # If any chunk produced a vector of different length, skip it
        if len(vec) != dim:
            continue
        for i in range(dim):
            summed[i] += vec[i]

    count = len(embeddings)
    if count == 0:
        return _embed_once("")
    return [v / count for v in summed]

