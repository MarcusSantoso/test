#!/usr/bin/env python3
"""Fill missing rmp_url values in .data/professors.csv.

For rows where the `rmp_url` column is empty, this script will generate a
RateMyProfessors search URL using the professor's name and write the updated
CSV back to the same path (making a backup first).
"""
import csv
import shutil
from urllib.parse import quote_plus

SRC = ".data/professors.csv"
BACKUP = ".data/professors.csv.bak"

def make_search_url(name: str) -> str:
    # Use a RMP search URL as a placeholder so links point somewhere useful.
    q = quote_plus(name.strip())
    return f"https://www.ratemyprofessors.com/search/teachers?query={q}"

def main():
    shutil.copyfile(SRC, BACKUP)
    rows = []
    with open(SRC, newline='') as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        for r in reader:
            # Normalize missing rmp_url (empty string or None)
            if r.get('rmp_url') is None or r.get('rmp_url').strip() == "":
                name = r.get('name') or ''
                if name.strip():
                    r['rmp_url'] = make_search_url(name)
                else:
                    r['rmp_url'] = ''
            rows.append(r)

    with open(SRC, 'w', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Updated {SRC}. Backup written to {BACKUP}.")

if __name__ == '__main__':
    main()
