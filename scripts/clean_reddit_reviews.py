#!/usr/bin/env python3
"""Clean Reddit reviews that don't include the professor's full name and a course mention.

Usage:
  # Dry run (default) - shows counts and examples
  python scripts/clean_reddit_reviews.py

  # Actually delete matching reviews from the DB
  python scripts/clean_reddit_reviews.py --commit

The script connects to the application's database using the same logic
as the application (reads env vars and falls back to localhost defaults).
It only deletes reviews whose `source` contains 'reddit' (case-insensitive)
AND whose text does not contain BOTH the professor's full name (case-insensitive)
AND a course-code-like mention (e.g. "STAT 201", "CMPT105", "MATH-100").

By default this script only prints what it would delete (dry-run). Pass
`--commit` to perform the deletions. The script also writes a CSV log of
removed review ids when committing.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from typing import Optional

from src.shared.database import get_db
from src.user_service.models import Review, Professor

COURSE_PATTERN = re.compile(r"\b[A-Z]{2,6}\s*-?\s*\d{2,4}\w*\b")


def contains_full_name(text: str | None, full_name: str | None) -> bool:
    if not text or not full_name:
        return False
    try:
        return re.search(r"\b" + re.escape(full_name) + r"\b", text, flags=re.IGNORECASE) is not None
    except Exception:
        return False


def contains_course_mention(text: str | None) -> bool:
    if not text:
        return False
    return bool(COURSE_PATTERN.search(text.upper()))


def main(commit: bool = False, sample_limit: int = 5):
    db = next(get_db())
    try:
        # Query reddit-sourced reviews (case-insensitive contains)
        q = db.query(Review).filter(Review.source.ilike('%reddit%'))
        total = q.count()
        print(f"Found {total} reviews with source LIKE '%reddit%'. Scanning...")

        to_remove = []
        keep = []
        examples_remove = []
        examples_keep = []

        for rv in q.yield_per(200):
            prof: Optional[Professor] = db.get(Professor, rv.prof_id)
            prof_name = getattr(prof, 'name', None)
            text = (rv.text or "").strip()

            has_name = contains_full_name(text, prof_name)
            has_course = contains_course_mention(text)

            # Only keep reddit reviews that include BOTH the full professor
            # name and mention at least one course code/token. Otherwise mark
            # for removal.
            if has_name and has_course:
                keep.append(rv.id)
                if len(examples_keep) < sample_limit:
                    examples_keep.append((rv.id, prof_name, text[:200]))
            else:
                to_remove.append(rv.id)
                if len(examples_remove) < sample_limit:
                    examples_remove.append((rv.id, prof_name, text[:200], has_name, has_course))

        print(f"Will remove {len(to_remove)} reviews (dry-run={not commit}).")
        if examples_remove:
            print("\nExamples of reviews to be removed (id, prof_name, preview, has_name, has_course):")
            for ex in examples_remove:
                print(ex)

        if examples_keep:
            print("\nExamples of reviews to be kept (id, prof_name, preview):")
            for ex in examples_keep:
                print(ex)

        if not to_remove:
            print("Nothing to remove. Exiting.")
            return 0

        if not commit:
            print("Dry-run complete. No changes made. Rerun with --commit to delete the above reviews.")
            return 0

        # Delete in batches to avoid loading huge memory
        LOG_PATH = 'scripts/removed_reddit_reviews.csv'
        with open(LOG_PATH, 'w', newline='', encoding='utf-8') as csvf:
            writer = csv.writer(csvf)
            writer.writerow(['review_id', 'prof_id', 'prof_name', 'preview'])

            BATCH = 200
            for i in range(0, len(to_remove), BATCH):
                batch = to_remove[i:i+BATCH]
                # fetch objects and delete
                rows = db.query(Review).filter(Review.id.in_(batch)).all()
                for r in rows:
                    p = db.get(Professor, r.prof_id)
                    writer.writerow([r.id, r.prof_id, getattr(p, 'name', None), (r.text or '')[:200]])
                    db.delete(r)
                db.commit()
        print(f"Deleted {len(to_remove)} reviews and wrote log to {LOG_PATH}.")
        return 0
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--commit', action='store_true', help='Actually delete matching reviews from DB')
    parser.add_argument('--sample', type=int, default=5, help='Number of examples to print')
    args = parser.parse_args()
    sys.exit(main(commit=args.commit, sample_limit=args.sample))
