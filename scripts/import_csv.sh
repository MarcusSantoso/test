#!/usr/bin/env bash
set -euo pipefail

# Safe CSV import helper. Loads CSVs into temporary staging tables,
# upserts into main tables, then runs VACUUM ANALYZE.
#
# Usage: ./scripts/import_csv.sh
# Ensure the DATABASE_URL env var is set, e.g.:
# export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/user_service"

if [ -z "${DATABASE_URL:-}" ]; then
  echo "Please set DATABASE_URL, e.g. postgresql://postgres:postgres@localhost:5432/user_service"
  exit 1
fi

echo "Using DATABASE_URL=$DATABASE_URL"


echo "Creating staging tables, loading CSVs, and running upserts in a single psql session..."
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<'PSQL'
CREATE TEMP TABLE stg_professors (id bigint, name text, department text, rmp_url text, created_at text, updated_at text, course_codes text);
CREATE TEMP TABLE stg_reviews (id bigint, prof_id bigint, text text, source text, "timestamp" text, rating text);

\copy stg_professors(id,name,department,rmp_url,created_at,updated_at,course_codes) FROM './.data/professors.csv' CSV HEADER
\copy stg_reviews(id,prof_id,text,source,"timestamp",rating) FROM './.data/reviews.csv' CSV HEADER

-- Upsert professors
BEGIN;
INSERT INTO professors (id, name, department, rmp_url, created_at, updated_at, course_codes)
SELECT id::integer, name, department, rmp_url,
       NULLIF(created_at, '')::timestamp,
       NULLIF(updated_at, '')::timestamp,
       course_codes
FROM stg_professors
ON CONFLICT (id) DO UPDATE
  SET name = EXCLUDED.name,
      department = EXCLUDED.department,
      rmp_url = EXCLUDED.rmp_url,
      created_at = COALESCE(EXCLUDED.created_at, professors.created_at),
      updated_at = EXCLUDED.updated_at,
      course_codes = EXCLUDED.course_codes;

-- Upsert reviews
INSERT INTO reviews (id, prof_id, text, source, "timestamp", rating)
SELECT id::integer, prof_id::integer, text, source, NULLIF("timestamp", '')::timestamp, NULLIF(rating, '')::integer
FROM stg_reviews
ON CONFLICT (id) DO UPDATE
  SET prof_id = EXCLUDED.prof_id,
      text = EXCLUDED.text,
      source = EXCLUDED.source,
      "timestamp" = EXCLUDED."timestamp",
      rating = EXCLUDED.rating;

COMMIT;

VACUUM ANALYZE professors;
VACUUM ANALYZE reviews;

PSQL

echo "Import (staging -> upsert) finished." 

echo "Import complete."
