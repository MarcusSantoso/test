#!/usr/bin/env python3
"""Convert all rmp_url values in `.data/professors.csv` to
`https://www.ratemyprofessors.com/ShowRatings.jsp?tid=<id>` using the
professor `id` column. Creates a timestamped backup before writing.
"""
import csv
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_CSV = ROOT / ".data" / "professors.csv"


def main():
    if not DATA_CSV.exists():
        print(f"ERROR: {DATA_CSV} not found")
        return 2

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    backup = DATA_CSV.with_suffix(f".csv.bak.{ts}")
    shutil.copy2(DATA_CSV, backup)
    print(f"Backup written to: {backup}")

    rows = []
    with DATA_CSV.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if fieldnames is None:
            print("ERROR: couldn't read CSV header")
            return 3
        for r in reader:
            # Use the CSV's `id` field as the tid value. If missing, keep existing.
            pid = r.get('id')
            if pid and pid.strip():
                r['rmp_url'] = f"https://www.ratemyprofessors.com/ShowRatings.jsp?tid={pid.strip()}"
            rows.append(r)

    # Write back preserving header order
    with DATA_CSV.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Updated {len(rows)} rows in {DATA_CSV}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
