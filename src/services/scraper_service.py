from __future__ import annotations

import hashlib
from datetime import datetime
from typing import List, Iterable
import time

import httpx
from urllib.parse import quote
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.shared.database import get_db

from src.user_service.models import Review, Professor


USER_AGENT = "user_service_scraper/1.0 (+https://example.com)"

GRAPHQL_URL = "https://www.ratemyprofessors.com/graphql"

# Known identifiers for Simon Fraser University (used for filtering/searching)
# If you have a canonical GraphQL `school.id` for SFU you can set it here.
SFU_SCHOOL_NAME = "Simon Fraser University"
# Canonical SFU GraphQL node id (from RateMyProfessors `newSearch` schools query)
SFU_SCHOOL_GRAPHQL_ID: str | None = "U2Nob29sLTE0ODI="

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
                # include subreddit info when available (helps whitelist filtering)
                subreddit = d.get("subreddit") or d.get("subreddit_name_prefixed") or None
                out.append({
                    "text": text.strip(),
                    "timestamp": datetime.fromtimestamp(created) if created else None,
                    "source": "reddit",
                    "rating": None,
                    "subreddit": subreddit,
                })
    except Exception:
        # best-effort: return what we have or empty
        return out
    return out


def list_sfu_professors(limit_per_letter: int = 200, tokens: Iterable[str] | None = None, delay: float = 0.0, max_requests: int | None = None) -> List[dict]:
    """Return a list of professor summaries for Simon Fraser University (SFU).

    By default this runs searches for the vowel tokens ['a','e','i','o','u'].
    Parameters:
    - `limit_per_letter`: number passed as `first` to each GraphQL query.
    - `tokens`: iterable of strings to use as `text` queries. If None defaults
      to vowels.
    - `delay`: seconds to sleep between GraphQL requests.
    - `max_requests`: optional cap on number of GraphQL requests.
    Results are deduplicated by `legacyId`.
    """
    out: List[dict] = []

    if tokens is None:
        tokens = ["a", "e", "i", "o", "u"]
    else:
        tokens = list(tokens)

    search_q = '''
query($text:String!,$first:Int){
  newSearch {
    teachers(query:{text:$text}, first:$first) {
      edges { node { id firstName lastName legacyId department numRatings avgRatingRounded school { id name } courseCodes { courseName } } }
    }
  }
}
'''

    seen = set()
    requests = 0

    for idx, tok in enumerate(tokens):
        if max_requests is not None and requests >= max_requests:
            break
        resp = _graphql_request(search_q, {"text": tok, "first": limit_per_letter})
        requests += 1
        if delay and idx != len(tokens) - 1:
            try:
                time.sleep(delay)
            except Exception:
                pass

        if not resp or "data" not in resp:
            continue
        edges = resp.get("data", {}).get("newSearch", {}).get("teachers", {}).get("edges") or []
        for e in edges:
            node = e.get("node") or {}
            school = (node.get("school") or {}).get("name") or ""
            if SFU_SCHOOL_NAME.lower() not in school.lower():
                continue
            legacy = node.get("legacyId")
            if legacy in seen or legacy is None:
                continue
            seen.add(legacy)

            fn = node.get("firstName") or ""
            ln = node.get("lastName") or ""
            full = f"{fn} {ln}".strip()
            course_codes = [c.get("courseName") for c in (node.get("courseCodes") or []) if c.get("courseName")]

            out.append({
                "name": full,
                "firstName": fn,
                "lastName": ln,
                "legacyId": legacy,
                "school_name": school,
                "department": node.get("department"),
                "numRatings": node.get("numRatings"),
                "avgRatingRounded": node.get("avgRatingRounded"),
                "courseCodes": course_codes,
                "id": node.get("id"),
            })

    return out


def list_all_sfu_professors(limit_per_letter: int = 200, delay: float = 0.15, max_requests: int | None = None) -> List[dict]:
    """Collect SFU professors by running `newSearch` over tokens 'a'..'z'.

    - `limit_per_letter`: `first` per query
    - `delay`: seconds between requests
    - `max_requests`: cap on total queries
    """
    tokens = [chr(c) for c in range(ord('a'), ord('z') + 1)]
    return list_sfu_professors(limit_per_letter=limit_per_letter, tokens=tokens, delay=delay, max_requests=max_requests)


if __name__ == "__main__":
    # quick manual test: print first 20 SFU professors
    try:
        profs = list_sfu_professors(limit=200)
        print(f"Found {len(profs)} SFU professors (sample up to 20):")
        for i, p in enumerate(profs[:20], 1):
            print(i, p.get("legacyId"), p.get("name"), "->", p.get("department"), "courses:", p.get("courseCodes")[:3])
    except Exception as exc:
        print("Error listing SFU professors:", exc)


def import_sfu_professors_to_db(
    db: Session | None = None,
    limit_per_letter: int = 200,
    batch_size: int = 100,
    commit: bool = False,
    run_scrape: bool = False,
    *,
    delay: float = 0.0,
    max_requests: int | None = None,
    max_professors: int | None = None,
    max_reddit_per_prof: int | None = None,
    tokens: Iterable[str] | None = None,
) -> dict:
    """Import SFU professors from RateMyProfessors into the local `professors` table.

    Parameters:
    - `db`: a SQLAlchemy Session (if None the caller should provide one via `get_db()`)
    - `limit_per_letter`: number passed as `first` to each GraphQL query
    - `batch_size`: commit every `batch_size` inserts when `commit=True`
    - `commit`: if True, commit changes to the DB; otherwise run a dry-run and roll back
    - `delay`: seconds to wait between GraphQL requests when listing professors
    - `max_requests`: optional cap on number of GraphQL requests (useful for testing)
    - `tokens`: optional iterable of tokens to search (defaults to vowels in `list_sfu_professors`)

    Returns a dict: {added: int, skipped: int, errors: int, total_found: int}
    """
    # If caller didn't provide a DB session, create one from the app's DB
    close_db_gen = False
    db_gen = None
    if db is None:
        db_gen = get_db()
        db = next(db_gen)
        close_db_gen = True

    profs = list_sfu_professors(limit_per_letter=limit_per_letter, tokens=tokens, delay=delay, max_requests=max_requests)
    added = 0
    skipped = 0
    errors = 0
    processed = 0

    # Helper: use name+department as a uniqueness heuristic
    from sqlalchemy import select

    for i, p in enumerate(profs, 1):
        name = (p.get("name") or "").strip()
        dept = p.get("department")
        rmp_url = None
        legacy = p.get("legacyId")
        # collect course codes if present from the RMP node
        course_codes = p.get("courseCodes") or []
        # Normalize to list of strings and try to ensure department prefix (e.g. 'CMPT120')
        course_codes = [c for c in course_codes if c]
        try:
            import re
            normalized_codes = []
            for c in course_codes:
                s = str(c).strip()
                if not s:
                    continue
                # If already starts with letters (e.g. 'CMPT 120' or 'CMPT120'), normalize spacing and casing
                if re.match(r'^[A-Za-z]', s):
                    normalized_codes.append(re.sub(r"\s+", "", s).upper())
                elif re.match(r'^\d{2,3}$', s) and p.get("department"):
                    # only digits -> prefix with department if available
                    normalized_codes.append(f"{p.get('department').upper()}{s}")
                else:
                    normalized_codes.append(s.upper())
            course_codes = normalized_codes
        except Exception:
            # keep original best-effort
            course_codes = [str(c).strip() for c in course_codes if c]
        if legacy:
            rmp_url = f"https://www.ratemyprofessors.com/ShowRatings.jsp?tid={legacy}"

        if not name:
            skipped += 1
            continue

        try:
            # check existing professor by exact name + department
            stmt = select(Professor).where(Professor.name == name)
            if dept:
                stmt = stmt.where(Professor.department == dept)
            existing = db.scalars(stmt.limit(1)).first()
            if existing:
                skipped += 1
                continue

            import json

            prof = Professor(name=name, department=dept, rmp_url=rmp_url, course_codes=(json.dumps(course_codes) if course_codes else None))
            db.add(prof)
            # flush/commit to get id assigned so we can call scrapers
            try:
                db.flush()
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
            # If commit True, commit in batches for Postgres performance
            if commit:
                if i % batch_size == 0:
                    try:
                        db.commit()
                        added += batch_size
                    except Exception:
                        db.rollback()
                        errors += batch_size
                else:
                    # defer commit until batch boundary
                    pass
            else:
                # dry-run: flush so we can detect DB-level errors
                try:
                    db.flush()
                    added += 1
                except Exception:
                    db.rollback()
                    errors += 1

        except Exception:
            errors += 1
            try:
                db.rollback()
            except Exception:
                pass

    # Finalize: if commit mode, commit remaining; if dry-run, rollback
            if commit:
                try:
                    db.commit()
                except Exception:
                    try:
                        db.rollback()
                    except Exception:
                        pass
            else:
                try:
                    db.rollback()
                except Exception:
                    pass

        # optionally run scrapers per professor to collect reviews (best-effort)
        try:
            # obtain the professor id from DB (may be newly flushed or committed)
            stmt = select(Professor).where(Professor.name == name)
            if dept:
                stmt = stmt.where(Professor.department == dept)
            prof_row = db.scalars(stmt.limit(1)).first()
            if prof_row and run_scrape:
                try:
                    scrape_professor_by_id(db, prof_row.id, strict_reddit=True, max_reddit=max_reddit_per_prof)
                except Exception:
                    errors += 1
        except Exception:
            # ignore scraping errors at import time
            pass

        processed += 1
        if max_professors is not None and processed >= max_professors:
            break
    else:
        try:
            db.rollback()
        except Exception:
            pass

    # close session we created from get_db()
    if close_db_gen and db_gen is not None:
        try:
            db_gen.close()
        except Exception:
            pass

    return {"added": added, "skipped": skipped, "errors": errors, "total_found": len(profs)}


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


def _graphql_request(query: str, variables: dict | None = None) -> dict | None:
    headers = {"User-Agent": USER_AGENT}
    try:
        with httpx.Client(timeout=20.0, headers=headers) as client:
            r = client.post(GRAPHQL_URL, json={"query": query, "variables": variables or {}})
            r.raise_for_status()
            return r.json()
    except Exception:
        return None


def scrape_rmp_graphql(prof_name: str, school_name: str | None = None, limit: int = 200) -> List[dict]:
    """Search RateMyProfessors via GraphQL for a teacher matching `prof_name` and optional `school_name`.

    Returns list of normalized review dicts: {text, timestamp(datetime|None), source='ratemyprofessors', rating}
    """
    out: List[dict] = []

    # 1) search teachers
    search_q = '''
query($text:String!,$first:Int){
  newSearch {
    teachers(query:{text:$text}, first:$first) {
      edges { node { id firstName lastName legacyId department numRatings avgRatingRounded school { id name } courseCodes { courseName } } }
    }
  }
}
'''
    resp = _graphql_request(search_q, {"text": prof_name, "first": 50})
    if not resp or "data" not in resp:
        return out

    edges = resp.get("data", {}).get("newSearch", {}).get("teachers", {}).get("edges") or []
    # find best matching teacher node
    prof_name_norm = (prof_name or "").strip().lower()
    candidate = None
    for e in edges:
        node = e.get("node") or {}
        fn = (node.get("firstName") or "").strip().lower()
        ln = (node.get("lastName") or "").strip().lower()
        full = f"{fn} {ln}".strip()
        school = (node.get("school") or {}).get("name") or ""
        school_l = school.lower()
        # match by full name presence
        if prof_name_norm == full or prof_name_norm in full:
            if school_name:
                if school_name.lower() in school_l:
                    candidate = node
                    break
            else:
                candidate = node
                break

    if not candidate and edges:
        # fallback: pick first node whose full name contains the prof_name tokens
        for e in edges:
            node = e.get("node") or {}
            fn = (node.get("firstName") or "").strip().lower()
            ln = (node.get("lastName") or "").strip().lower()
            full = f"{fn} {ln}".strip()
            if all(p in full for p in prof_name_norm.split()):
                candidate = node
                break

    if not candidate:
        return out

    teacher_id = candidate.get("id")
    if not teacher_id:
        return out

    # 2) fetch ratings for the teacher node using cursor-based pagination
    node_q = '''
query($id:ID!,$first:Int,$after:String){
  node(id:$id){
    ... on Teacher {
      id firstName lastName legacyId school { id name } numRatings
      ratings(first:$first, after:$after) { edges { node { legacyId date comment qualityRating grade wouldTakeAgain } } pageInfo { endCursor hasNextPage } }
    }
  }
}
'''

    fetched = 0
    after = None
    page_size = 50 if limit > 50 else limit

    while fetched < limit:
        vars2 = {"id": teacher_id, "first": page_size}
        if after:
            vars2["after"] = after

        resp2 = _graphql_request(node_q, vars2)
        if not resp2 or "data" not in resp2:
            break

        ratings_obj = resp2.get("data", {}).get("node", {}).get("ratings") or {}
        rating_edges = ratings_obj.get("edges") or []

        for e in rating_edges:
            if fetched >= limit:
                break
            n = e.get("node") or {}
            text = n.get("comment") or ""
            date = n.get("date")
            ts = None
            if date:
                try:
                    from datetime import datetime

                    try:
                        ts = datetime.strptime(date, "%Y-%m-%d %H:%M:%S +0000 UTC")
                    except Exception:
                        try:
                            ts = datetime.fromisoformat(date)
                        except Exception:
                            ts = None
                except Exception:
                    ts = None

            out.append({"text": (text or "").strip(), "timestamp": ts, "source": "ratemyprofessors", "rating": n.get("qualityRating")})
            fetched += 1

        page_info = ratings_obj.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        after = page_info.get("endCursor")

    return out


def scrape_professor_by_id(db: Session, prof_id: int, *, course_code: str | None = None, require_fullname_and_school_and_course: bool = False, strict_reddit: bool = True, max_reddit: int | None = None) -> int:
    """Scrape sources for a given professor id and store new reviews.

    Returns number of reviews added.
    """
    prof = db.get(Professor, prof_id)
    if not prof:
        raise LookupError("Professor not found")

    added = 0
    reddit_inserted = 0
    if max_reddit is not None:
        try:
            existing_count = db.execute(text("select count(*) from reviews where prof_id=:pid and source='reddit'"), {"pid": prof_id}).scalar() or 0
        except Exception:
            existing_count = 0
    else:
        existing_count = 0

    sources: List[dict] = []
    # Prefer structured RateMyProfessors data first (higher quality)
    try:
        gql_items = scrape_rmp_graphql(prof.name, school_name=prof.department, limit=200)
        if gql_items:
            sources.extend(gql_items)
        else:
            sources.extend(scrape_rmp(prof.name, limit=200))
    except Exception:
        # best-effort fallback
        sources.extend(scrape_rmp(prof.name, limit=200))

    # Then supplement with Reddit results; apply stricter filtering below for reddit items
    sources.extend(scrape_reddit(prof.name, limit=200))

    for item in sources:
        norm = _normalize_review(item)
        text = norm["text"]
        timestamp = norm["timestamp"]
        source = norm["source"] or "unknown"
        rating = norm.get("rating")

        if not text:
            continue

        # For reddit items apply stricter heuristics to reduce false positives.
        if source == "reddit" and strict_reddit:
            txt = (text or "").lower()
            # Subreddit whitelist: if the post comes from a known SFU subreddit accept it
            subreddit = item.get("subreddit") or ""
            s = (subreddit or "").lower()
            if s.startswith("r/"):
                s_n = s[2:]
            else:
                s_n = s
            subreddit_whitelist = {"sfu", "simonfraseru", "sfubc", "sfucommunity"}
            if s_n and s_n in subreddit_whitelist:
                pass
            else:
                # require partial name match (first or last name token) AND either school or course mention
                name_tokens = [(t or "").lower() for t in (prof.name or "").split() if t]
                if not name_tokens:
                    continue
                # require at least one name token present (to avoid common-name noise)
                if not any(tok in txt for tok in name_tokens if len(tok) >= 2):
                    continue

                # require mention of SFU/CMPT or an explicit course code (e.g., 'CMPT 120') or provided course_code
                import re

                has_school = "sfu" in txt or "cmpt" in txt
                has_course_pattern = re.search(r"\bcmpt\s?\d{2,3}\b", txt) is not None
                has_provided_course = course_code and course_code.lower() in txt

                if not (has_school or has_course_pattern or has_provided_course):
                    # allow if subreddit whitelist matched earlier (handled above). Otherwise reject
                    continue

            # enforce reddit cap (count existing + inserted in this run)
            if max_reddit is not None:
                if (existing_count + reddit_inserted) >= max_reddit:
                    continue

        # duplicate prevention: exact match on text+timestamp+source
        if _is_duplicate(db, prof_id, text, timestamp, source):
            continue

        r = Review(prof_id=prof_id, text=text, source=source, timestamp=timestamp, rating=rating)
        db.add(r)
        try:
            db.commit()
            added += 1
            if source == 'reddit':
                reddit_inserted += 1
        except Exception:
            db.rollback()
            continue

    return added
