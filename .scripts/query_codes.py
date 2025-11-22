from src.shared.database import get_db
from sqlalchemy import text


def run_query(db, sql):
    try:
        return db.execute(text(sql)).scalars().all()
    except Exception as e:
        print('Query failed:', e)
        return []


def main():
    gen = get_db()
    db = next(gen)
    try:
        print('DB pre-check ->', db.execute(text('select 1')).scalar())

        sql_all_codes = "SELECT DISTINCT jsonb_array_elements_text(course_codes::jsonb) AS course_code FROM professors WHERE course_codes IS NOT NULL"
        codes = run_query(db, sql_all_codes)
        codes = [c for c in codes if c is not None]
        codes_sorted = sorted(set([c.strip() for c in codes]))
        print('\nDistinct course codes (total distinct):', len(codes_sorted))
        for c in codes_sorted:
            print(c)

        sql_cmpt = (
            "SELECT DISTINCT c.code FROM professors p, LATERAL jsonb_array_elements_text(p.course_codes::jsonb) AS c(code) "
            "WHERE c.code ILIKE 'CMPT%' ORDER BY c.code"
        )
        cmpt = run_query(db, sql_cmpt)
        cmpt_sorted = sorted(set([c.strip() for c in cmpt]))
        print('\nDistinct CMPT course codes (count):', len(cmpt_sorted))
        for c in cmpt_sorted:
            print(c)

        sql_dept = "SELECT department, count(*) FROM professors GROUP BY department ORDER BY count DESC LIMIT 20"
        dept_rows = db.execute(text(sql_dept)).all()
        print('\nTop departments (professor counts):')
        for d, cnt in dept_rows:
            print(f'{d}: {cnt}')

    finally:
        try:
            gen.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
