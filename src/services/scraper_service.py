from __future__ import annotations

import hashlib
from datetime import datetime
from typing import List

import httpx
from urllib.parse import quote
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.user_service.models import Review, Professor


USER_AGENT = "user_service_scraper/1.0 (+https://example.com)"


def _normalize_review(item: dict) -> dict:
    """Ensure review dict has text, timestamp (datetime), source, rating."""
    text = item.get("text") or ""
    ts = item.get("timestamp")
    if isinstance(ts, (int, float)):
        ts = datetime.fromtimestamp(ts)
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except Exception:
            ts = None

    return {"text": text.strip(), "timestamp": ts, "source": item.get("source"), "rating": item.get("rating")}


def _is_duplicate(db: Session, prof_id: int, text: str, timestamp: datetime, source: str) -> bool:
    # Basic duplicate prevention by exact match on text + timestamp + source
    stmt = select(Review).where(
        Review.prof_id == prof_id,
        Review.text == text,
        Review.source == source,
        Review.timestamp == timestamp,
    )
    return db.scalar(stmt) is not None


def _hash_text_timestamp_source(text: str, timestamp: datetime | None, source: str) -> str:
    ts = timestamp.isoformat() if timestamp is not None else ""
    key = f"{text}\n{ts}\n{source}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def scrape_reddit(prof_name: str, limit: int = 100) -> List[dict]:
    """Scrape Reddit search results for professor name using public search.json."""
    out: List[dict] = []
    query = prof_name
    url = f"https://www.reddit.com/search.json?q={quote(query)}&limit={limit}"
    headers = {"User-Agent": USER_AGENT}
    try:
        with httpx.Client(timeout=15.0, headers=headers) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.json()
            for child in data.get("data", {}).get("children", []):
                d = child.get("data", {})
                text = (d.get("title") or "") + "\n" + (d.get("selftext") or "")
                created = d.get("created_utc")
                out.append({"text": text.strip(), "timestamp": datetime.fromtimestamp(created) if created else None, "source": "reddit", "rating": None})
    except Exception:
        # best-effort: return what we have or empty
        return out
    return out


def scrape_rmp(prof_name: str, limit: int = 50) -> List[dict]:
    """Attempt to scrape RateMyProfessors search results and reviews (best-effort).

    This uses the public search page to find a professor id, then attempts to
    fetch review snippets from the professor page. It's fragile but works
    in many cases without authentication.
    """
    out: List[dict] = []
    headers = {"User-Agent": USER_AGENT}
    search_url = f"https://www.ratemyprofessors.com/search/teachers?query={quote(prof_name)}"
    try:
        with httpx.Client(timeout=15.0, headers=headers, follow_redirects=True) as client:
            r = client.get(search_url)
            r.raise_for_status()
            text = r.text
            # find first professor link containing '/ShowRatings.jsp?tid=' or '/professor/'
            # Try to locate tid or professor ID via simple heuristics
            import re

            m = re.search(r"/(ShowRatings|ProfessorRatings)\.jsp\?tid=(\d+)", text)
            if m:
                tid = m.group(2)
                prof_page = client.get(f"https://www.ratemyprofessors.com/ShowRatings.jsp?tid={tid}")
                prof_page.raise_for_status()
                page_text = prof_page.text
                # extract review blocks (simple heuristic for quotes)
                reviews = re.findall(r"<div class=\"Rating__RatingBody\">(.*?)</div>", page_text, flags=re.S)
                for rev in reviews[:limit]:
                    clean = re.sub(r"<[^>]+>", "", rev).strip()
                    out.append({"text": clean, "timestamp": None, "source": "ratemyprofessors", "rating": None})
            else:
                # try new path style: look for /professor/<id>
                m2 = re.search(r"/professor/(\d+)", text)
                if m2:
                    pid = m2.group(1)
                    prof_page = client.get(f"https://www.ratemyprofessors.com/professor/{pid}")
                    prof_page.raise_for_status()
                    page_text = prof_page.text
                    import re
                    reviews = re.findall(r"<p class=\"Comments__Text\">(.*?)</p>", page_text, flags=re.S)
                    for rev in reviews[:limit]:
                        clean = re.sub(r"<[^>]+>", "", rev).strip()
                        out.append({"text": clean, "timestamp": None, "source": "ratemyprofessors", "rating": None})
    except Exception:
        return out
    return out


def scrape_professor_by_id(db: Session, prof_id: int) -> int:
    """Scrape sources for a given professor id and store new reviews.

    Returns number of reviews added.
    """
    prof = db.get(Professor, prof_id)
    if not prof:
        raise LookupError("Professor not found")

    added = 0

    sources = []
    # Reddit
    sources.extend(scrape_reddit(prof.name, limit=200))
    # RateMyProfessors
    sources.extend(scrape_rmp(prof.name, limit=200))

    for item in sources:
        norm = _normalize_review(item)
        text = norm["text"]
        timestamp = norm["timestamp"]
        source = norm["source"] or "unknown"
        rating = norm.get("rating")

        if not text:
            continue

        # duplicate prevention: exact match on text+timestamp+source
        if _is_duplicate(db, prof_id, text, timestamp, source):
            continue

        r = Review(prof_id=prof_id, text=text, source=source, timestamp=timestamp, rating=rating)
        db.add(r)
        try:
            db.commit()
            added += 1
        except Exception:
            db.rollback()
            continue

    return added
