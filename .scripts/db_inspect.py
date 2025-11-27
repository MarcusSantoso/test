from src.shared.database import get_db
from sqlalchemy import text
import json

def print_table_sample(db, table, limit=10):
    try:
        res = db.execute(text(f"SELECT * FROM {table} LIMIT :limit"), {'limit': limit}).mappings().all()
        print(f"\n== {table} (showing up to {limit} rows) ==")
        if not res:
            print('(no rows)')
            return
        for r in res:
            print(json.dumps(dict(r), default=str))
    except Exception as e:
        print(f'Error reading table {table}:', e)


def main():
    gen = get_db()
    db = next(gen)
    try:
        print('DB pre-check ->', db.execute(text('select 1')).scalar())
        tables = [row[0] for row in db.execute(text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')"))]
        print('\nAvailable tables:')
        for t in tables:
            print('-', t)

        interest = ['professor','professors','review','reviews','reddit_post','reddit_posts']
        print('\nCounts and samples:')
        for name in interest:
            if name in tables:
                try:
                    cnt = db.execute(text(f'SELECT count(*) FROM {name}')).scalar()
                except Exception:
                    cnt = 'N/A'
                print(f"\n{name}: count={cnt}")
                print_table_sample(db, name, limit=10)
            else:
                print(f"\n{name}: (table not present)")

        if 'professors' in tables:
            print('\n== Sample professor rows (id,name,department,course_codes) ==')
            rows = db.execute(text('SELECT id, name, department, course_codes FROM professors ORDER BY id DESC LIMIT 20')).mappings().all()
            for r in rows:
                print(json.dumps(dict(r), default=str))

        if 'reviews' in tables:
            print('\n== Recent reviews (limit 20) ==')
            rows = db.execute(text('SELECT id, professor_id, source, rating, date, excerpt FROM reviews ORDER BY id DESC LIMIT 20')).mappings().all()
            for r in rows:
                print(json.dumps(dict(r), default=str))
    finally:
        try:
            gen.close()
        except Exception:
            pass

if __name__ == '__main__':
    main()
