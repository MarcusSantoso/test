-- Safe upsert script for staging -> main tables
-- This file is intended to be run after loading CSVs into
-- temporary tables `stg_professors` and `stg_reviews` via psql's \copy.

BEGIN;

-- Upsert professors
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

-- Notes:
-- - If you prefer to skip existing rows instead of overwriting, replace
--   `ON CONFLICT (id) DO UPDATE` with `ON CONFLICT (id) DO NOTHING`.
-- - `course_codes` here is treated as TEXT; if you later change it to JSONB,
--   you can cast: `course_codes::jsonb` in the INSERT SELECT.
