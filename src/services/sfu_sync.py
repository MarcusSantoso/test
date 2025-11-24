from __future__ import annotations

import argparse
import logging
import os
import time
from typing import Iterable, List

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session
import sys

from src.shared.database import get_db
from src.user_service.models import Professor
from src.services.scraper_service import scrape_professor_by_id

logger = logging.getLogger("sfu_sync")

# Base URL from SFU docs / your tests
# Examples:
#   GET {BASE}/course-outlines
#   GET {BASE}/course-outlines?2025
#   GET {BASE}/course-outlines?2025/summer
#   GET {BASE}/course-outlines?2015/summer/cmpt/110/c100
SFU_COURSE_OUTLINES_BASE = (
    os.environ.get("SFU_COURSE_OUTLINES_BASE")
    or "https://www.sfu.ca/bin/wcm"   # prefer https by default
)

DEFAULT_DEPARTMENT = "CMPT"
DEFAULT_RECENT_TERMS = 2


def _http_get_json(path: str, timeout: float = 20.0) -> dict | list | None:
    """Small helper to GET JSON from SFU Course Outlines."""
    url = SFU_COURSE_OUTLINES_BASE.rstrip("/") + path
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(url)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.exception("HTTP GET failed for %s: %s", url, exc)
        return None


def get_years() -> List[str]:
    """Return list of years as strings, e.g. ['2014', '2015', ...]."""
    data = _http_get_json("/course-outlines")
    if not data or not isinstance(data, list):
        return []
    years: list[str] = []
    for item in data:
        if isinstance(item, dict):
            year = item.get("value") or item.get("text")
        else:
            year = str(item)
        if year:
            years.append(str(year))
    return years


def get_terms(year: str) -> List[str]:
    """Return list of term codes like ['fall', 'spring', 'summer'] for a given year."""
    # e.g. GET /course-outlines?2025
    data = _http_get_json(f"/course-outlines?{year}")
    if not data or not isinstance(data, list):
        return []
    terms: list[str] = []
    for item in data:
        if isinstance(item, dict):
            term = item.get("value") or item.get("text")  # 'fall' vs 'FALL'
        else:
            term = str(item)
        if term:
            terms.append(str(term).lower())
    return terms


def get_course_numbers(year: str, term: str, department: str = DEFAULT_DEPARTMENT) -> List[str]:
    """Return list of course numbers like ['110', '120', ...] for dept/year/term."""
    # e.g. GET /course-outlines?2015/summer/cmpt
    path = f"/course-outlines?{year}/{term}/{department.lower()}"
    data = _http_get_json(path)
    if not data or not isinstance(data, list):
        return []
    out: list[str] = []
    for item in data:
        if isinstance(item, dict):
            num = item.get("value") or item.get("text")
        else:
            num = str(item)
        if num:
            out.append(str(num))
    return out


def get_departments(year: str, term: str) -> List[str]:
    """Return list of department codes available for a given year/term.

    This calls `/course-outlines?{year}/{term}` and attempts to parse
    department identifiers from the returned list.
    """
    path = f"/course-outlines?{year}/{term}"
    data = _http_get_json(path)
    if not data or not isinstance(data, list):
        return []
    out: list[str] = []
    for item in data:
        if isinstance(item, dict):
            val = item.get("value") or item.get("text")
        else:
            val = str(item)
        if val:
            out.append(str(val))
    return out


def get_course_sections(year: str, term: str, department: str, course_number: str) -> List[dict]:
    """Return list of section descriptors (dicts) for a given course."""
    # e.g. GET /course-outlines?2015/summer/cmpt/110
    path = f"/course-outlines?{year}/{term}/{department.lower()}/{course_number}"
    data = _http_get_json(path)
    if not data or not isinstance(data, list):
        return []
    # we keep as list[dict] to let caller extract section codes
    return data


def get_course_outline(year: str, term: str, department: str, course_number: str, section: str) -> dict | None:
    """Return full course outline JSON for a given section."""
    # e.g. GET /course-outlines?2015/summer/cmpt/110/c100
    path = f"/course-outlines?{year}/{term}/{department.lower()}/{course_number}/{section}"
    data = _http_get_json(path)
    if not isinstance(data, dict):
        return None
    return data



def _extract_instructors_from_outline(obj) -> List[str]:
    """Recursively search outline JSON for instructor information.

    Returns a list of instructor full-name strings.
    """
    out: List[str] = []

    if obj is None:
        return out

    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = k.lower()
            if lk in ("instructors", "instructor", "primaryinstructor", "instructorlist"):
                # handle list/dict/string
                if isinstance(v, list):
                    for it in v:
                        if isinstance(it, dict):
                            fn = it.get("firstName") or it.get("firstname") or it.get("givenName") or ""
                            ln = it.get("lastName") or it.get("lastname") or it.get("familyName") or ""
                            name = (f"{fn} {ln}".strip()) or it.get("name") or it.get("displayName")
                            if name:
                                out.append(name)
                        elif isinstance(it, str):
                            out.append(it)
                elif isinstance(v, dict):
                    fn = v.get("firstName") or v.get("firstname") or v.get("givenName") or ""
                    ln = v.get("lastName") or v.get("lastname") or v.get("familyName") or ""
                    name = (f"{fn} {ln}".strip()) or v.get("name") or v.get("displayName")
                    if name:
                        out.append(name)
                elif isinstance(v, str):
                    out.append(v)
            else:
                out.extend(_extract_instructors_from_outline(v))
    elif isinstance(obj, list):
        for it in obj:
            out.extend(_extract_instructors_from_outline(it))

    # dedupe preserving order
    seen = set()
    deduped = []
    for name in out:
        if not name:
            continue
        n = " ".join(name.split())
        if n not in seen:
            seen.add(n)
            deduped.append(n)
    return deduped


def sync_sfu_instructors_to_db(
    db: Session,
    department: str = DEFAULT_DEPARTMENT,
    recent_terms: int = DEFAULT_RECENT_TERMS,
    max_courses: int | None = None,
    pause_between_requests: float = 0.08,
    commit: bool = False,
    *,
    all_years: bool = False,
    all_departments: bool = False,
    no_scrape: bool = False,
    max_reddit: int | None = None,
) -> dict:
    """Main sync routine.

    - Scans recent terms for `department` courses, pulls outlines, extracts instructors,
      creates Professor rows if missing, and optionally runs `scrape_professor_by_id`.
    - Returns summary dict.
    """
    result = {"professors_seen": 0, "created": 0, "skipped": 0, "scraped_reviews_added": 0, "errors": 0}

    years = get_years()
    if not years:
        logger.error("Could not fetch years from SFU API; aborting")
        return result

    years_sorted = sorted(years, reverse=True)
    if all_years:
        years_to_scan = years_sorted
        logger.info("Syncing SFU department=%s for ALL years: %s", department, years_to_scan)
    else:
        # choose most recent year and its recent N terms
        latest_year = years_sorted[0]
        terms = get_terms(latest_year)
        if not terms:
            logger.error("No terms for year %s", latest_year)
            return result
        recent = terms[:recent_terms]
        years_to_scan = [latest_year]
        logger.info("Syncing SFU department=%s for year=%s terms=%s", department, latest_year, recent)

    courses_processed = 0

    for year in years_to_scan:
        # determine which terms to scan for this year
        terms = get_terms(year)
        if not terms:
            logger.info("No terms for year %s", year)
            continue
        if all_years:
            terms_to_scan = terms
        else:
            terms_to_scan = recent

        for term in terms_to_scan:
            # Determine departments to scan: single department or discover all
            departments_to_scan: List[str]
            if all_departments:
                departments_to_scan = get_departments(year, term)
            else:
                departments_to_scan = [department]

            for dept in departments_to_scan:
                course_numbers = get_course_numbers(year, term, dept)
            if not course_numbers:
                logger.info("No course numbers for %s %s %s", year, term, dept)
                continue
            for cn in course_numbers:
                if max_courses is not None and courses_processed >= max_courses:
                    break
                sections = get_course_sections(year, term, department, cn)
                if not sections:
                    continue
                for sec in sections:
                    # section may be dict with 'value' / 'section' / 'text'
                    if isinstance(sec, dict):
                        section_code = (
                            sec.get("value")
                            or sec.get("section")
                            or sec.get("text")
                        )
                    else:
                        section_code = str(sec)
                    if not section_code:
                        continue
                    outline = get_course_outline(year, term, department, cn, section_code)
                    if not outline:
                        continue
                    instructors = _extract_instructors_from_outline(outline)
                    result["professors_seen"] += len(instructors)
                    for name in instructors:
                        try:
                            # simple uniqueness: exact name + department
                            stmt = select(Professor).where(Professor.name == name)
                            existing = db.scalars(stmt.limit(1)).first()
                            if existing:
                                result["skipped"] += 1
                                prof = existing
                            else:
                                # store the course number(s) associated with this outline
                                import json
                                try:
                                    # Normalize course code to include department prefix (e.g. 'CMPT110')
                                    prof_course_codes = []
                                    if cn:
                                        cc = str(cn).strip()
                                        if not str(dept).upper() in cc.upper():
                                            prof_course_codes = [f"{str(dept).upper()}{cc}"]
                                        else:
                                            prof_course_codes = [cc.upper()]
                                except Exception:
                                    prof_course_codes = []
                                prof = Professor(name=name, department=department, rmp_url=None, course_codes=(json.dumps(prof_course_codes) if prof_course_codes else None))
                                db.add(prof)
                                if commit:
                                    db.commit()
                                    db.refresh(prof)
                                else:
                                    # flush to assign PK in dry-run mode
                                    try:
                                        db.flush()
                                        db.refresh(prof)
                                    except Exception:
                                        # ignore assign issues on dry-run
                                        pass
                                result["created"] += 1

                            # If an existing professor lacks this course code, append it
                            try:
                                import json as _json
                                if existing and cn:
                                    # normalize incoming code similar to insert time
                                    cc = str(cn).strip()
                                    normalized = cc.upper()
                                    if not str(dept).upper() in normalized:
                                        normalized = f"{str(dept).upper()}{normalized}"

                                    current = getattr(prof, "course_codes", None)
                                    if current:
                                        try:
                                            lst = _json.loads(current)
                                        except Exception:
                                            lst = []
                                    else:
                                        lst = []
                                    if normalized not in lst:
                                        lst.append(normalized)
                                        prof.course_codes = _json.dumps(lst)
                                        if commit:
                                            try:
                                                db.commit()
                                            except Exception:
                                                db.rollback()
                            except Exception:
                                # ignore best-effort update failures
                                pass

                            # run scraping for the professor to gather reviews unless disabled
                            if not no_scrape:
                                try:
                                    added = scrape_professor_by_id(db, prof.id, max_reddit=max_reddit)
                                    result["scraped_reviews_added"] += added
                                except Exception:
                                    logger.exception("scrape_professor_by_id failed for %s", name)
                                    result["errors"] += 1

                        except Exception:
                            logger.exception("Failed to insert/scrape professor %s", name)
                            result["errors"] += 1

                    courses_processed += 1
                    if pause_between_requests:
                        time.sleep(pause_between_requests)

            if max_courses is not None and courses_processed >= max_courses:
                break

    return result


def _parse_args():
    p = argparse.ArgumentParser(prog="sfu_sync")
    p.add_argument("--department", default=DEFAULT_DEPARTMENT, help="Department code to sync (default CMPT)")
    p.add_argument("--recent-terms", type=int, default=DEFAULT_RECENT_TERMS, help="Number of recent terms to scan")
    p.add_argument("--max-courses", type=int, default=None, help="Cap how many courses to process (for testing)")
    p.add_argument(
        "--commit",
        action="store_true",
        help=(
            "Commit changes to DB (default is dry-run). Note: when not set, "
            "the CLI will attempt to use the app's DB but will fall back to "
            "an in-memory SQLite database for testing if DATABASE env vars "
            "are not present. Use --commit only when you have a real DB."
        ),
    )
    p.add_argument("--pause", type=float, default=0.08, help="Pause between outline requests (seconds)")
    p.add_argument("--all-departments", action="store_true", help="Discover and sync all departments instead of a single department")
    p.add_argument("--max-reddit", type=int, default=None, help="Limit reddit posts saved per professor (passed to scrapers)")
    p.add_argument("--all-years", action="store_true", help="Scan all available years/terms instead of only recent terms")
    p.add_argument("--no-scrape", action="store_true", help="Do not run scrapers after inserting professors (dry import only)")
    return p.parse_args()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    args = _parse_args()

    # Try to obtain a real DB session from the app. If that fails and
    # we're running a dry-run (no --commit), fall back to an in-memory
    # SQLite DB so the CLI remains useful for testing without requiring
    # DATABASE_* env vars.
    gen = None
    db = None
    if args.commit:
        # commit mode requires a real DB; attempt a short fast-connect check
        try:
            gen = get_db()
            db = next(gen)
            # do a fast check: execute a lightweight select 1
            try:
                bind = getattr(db, "get_bind", None)
                if bind is not None:
                    engine = db.get_bind()
                    with engine.connect() as conn:
                        conn.execute(text("select 1"))
                else:
                    # fallback: try executing via session.execute
                    db.execute(text("select 1"))
            except Exception as exc:
                logger.exception("Database connectivity check failed: %s", exc)
                print("ERROR: Could not connect to the database. Check DATABASE_* or POSTGRES_* env vars and network access.")
                try:
                    gen.close()
                except Exception:
                    pass
                sys.exit(2)
        except Exception as exc:
            logger.exception("Failed to obtain DB session for commit mode: %s", exc)
            print("ERROR: get_db() failed — ensure DATABASE_* or POSTGRES_* env vars are set and correct.")
            sys.exit(2)
    else:
        # prefer real DB if available, but fall back to memory for dry-runs
        try:
            gen = get_db()
            db = next(gen)
        except Exception:
            logger.warning("get_db() failed or DATABASE env not set; using in-memory SQLite for dry-run")
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from src.user_service.models import Base

            engine = create_engine("sqlite:///:memory:")
            Base.metadata.create_all(engine)
            SessionLocal = sessionmaker(bind=engine)
            db = SessionLocal()

    try:
        summary = sync_sfu_instructors_to_db(
            db,
            department=args.department,
            recent_terms=args.recent_terms,
            max_courses=args.max_courses,
            pause_between_requests=args.pause,
            commit=args.commit,
            all_years=args.all_years,
            all_departments=args.all_departments,
            no_scrape=args.no_scrape,
            max_reddit=args.max_reddit,
        )
        print("Summary:", summary)
    finally:
        # close the generator returned by get_db() if we created one
        if gen is not None:
            try:
                gen.close()
            except Exception:
                pass
