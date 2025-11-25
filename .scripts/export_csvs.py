from src.shared.database import get_db
from sqlalchemy import text
import csv
import os

OUT_DIR = '.data'
os.makedirs(OUT_DIR, exist_ok=True)

def export_table(db, table_name, out_file):
    with open(out_file, 'w', newline='', encoding='utf-8') as f:
        cur = db.execute(text(f'SELECT * FROM {table_name}'))
        rows = cur.mappings().all()
        if not rows:
            print(f'No rows for {table_name}, wrote empty file.')
            return 0
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            row = dict(r)
            # ensure JSON/text fields are string
            for k, v in row.items():
                if isinstance(v, (list, dict)):
                    row[k] = json.dumps(v)
            writer.writerow(row)
        return len(rows)

if __name__ == '__main__':
    gen = get_db()
    db = next(gen)
    try:
        for tbl in ('professors', 'reviews', 'ai_summaries'):
            try:
                out = os.path.join(OUT_DIR, f'{tbl}.csv')
                cnt = export_table(db, tbl, out)
                print(f'Wrote {cnt} rows to {out}')
            except Exception as e:
                print(f'Failed to export {tbl}:', e)
    finally:
        try:
            gen.close()
        except Exception:
            pass
