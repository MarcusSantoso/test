-- Sample sanitized dev data for user_service
-- Safe to include in repository: no emails, no API keys

BEGIN;

-- Professors (sanitized sample)
INSERT INTO professors (id, name, department, rmp_url, course_codes, created_at)
VALUES
  (1001, 'Diana Cukierman', 'CMPT', NULL, '["CMPT105w"]', now()),
  (1002, 'Herbert Tsang', 'CMPT', NULL, '["CMPT105w"]', now()),
  (1003, 'Toby Donaldson', 'CMPT', NULL, '["CMPT120"]', now()),
  (1004, 'Igor Shinkar', 'CMPT', NULL, '["CMPT125"]', now()),
  (1005, 'Example Prof', 'MATH', NULL, '["MATH100"]', now());

-- Reviews (sanitized sample)
INSERT INTO reviews (id, prof_id, text, source, timestamp, rating)
VALUES
  (2001, 1001, 'Excellent instructor; clear lectures.', 'rmp', now(), 5),
  (2002, 1002, 'Tough grader but fair.', 'reddit', now(), 4),
  (2003, 1003, 'Engaging and helpful.', 'rmp', now(), 5),
  (2004, 1004, 'Great course materials.', 'reddit', now(), 4);

-- Ensure sequences are up-to-date (Postgres serial sequences)
SELECT setval(pg_get_serial_sequence('professors','id'), (SELECT MAX(id) FROM professors));
SELECT setval(pg_get_serial_sequence('reviews','id'), (SELECT MAX(id) FROM reviews));

COMMIT;
