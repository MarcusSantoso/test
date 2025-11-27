#!/usr/bin/env bash
set -euo pipefail

# scripts/sync_db.sh
# Simple helper to copy a Postgres database from a host Postgres instance
# into the Docker Compose `db` service for local development.
#
# Usage:
#   ./scripts/sync_db.sh
#
# Environment variables (optional):
#   SRC_HOST (default 127.0.0.1)
#   SRC_PORT (default 5432)
#   SRC_USER (default postgres)
#   SRC_DB   (default user_service)
#   SRC_PG_PASSWORD or PGPASSWORD must be set (or POSTGRES_PASSWORD in .env)
#
# The script will:
#   1. Ensure the compose `db` service is available
#   2. Drop & recreate the `user_service` DB inside the compose db
#   3. Stream a pg_dump from the source into the compose db's psql

SRC_HOST=${SRC_HOST:-127.0.0.1}
SRC_PORT=${SRC_PORT:-5432}
SRC_USER=${SRC_USER:-postgres}
SRC_DB=${SRC_DB:-user_service}
DEST_DB=${DEST_DB:-user_service}

# Try to obtain password from environment or from .env file if present
: ${PGPASSWORD:=${SRC_PG_PASSWORD:-}}
if [ -z "${PGPASSWORD}" ] && [ -f .env ]; then
  # try to source POSTGRES_PASSWORD from .env as fallback
  PGPASSWORD=$(grep -E '^POSTGRES_PASSWORD=' .env | sed 's/^POSTGRES_PASSWORD=//') || true
fi

if [ -z "${PGPASSWORD}" ]; then
  echo "ERROR: PGPASSWORD or SRC_PG_PASSWORD or POSTGRES_PASSWORD in .env must be set"
  exit 1
fi

export PGPASSWORD

echo "==> Ensuring Docker Compose services are available"
docker compose ps db >/dev/null 2>&1 || { echo "docker compose services not available; run 'docker compose up -d'"; exit 1; }

echo "==> Dropping and recreating destination DB (${DEST_DB}) inside the compose db"
docker compose exec -T db dropdb -U postgres "${DEST_DB}" || true
docker compose exec -T db createdb -U postgres "${DEST_DB}"

echo "==> Streaming pg_dump from ${SRC_HOST}:${SRC_PORT}/${SRC_DB} into compose db (${DEST_DB})"
# Stream host pg_dump into the compose db psql to avoid temporary files
PGPASSWORD=${PGPASSWORD} pg_dump -h "${SRC_HOST}" -p "${SRC_PORT}" -U "${SRC_USER}" -d "${SRC_DB}" -F p | docker compose exec -T db psql -U postgres -d "${DEST_DB}"

echo "==> Done. Verifying count of professors in compose db"
docker compose exec -T db psql -U postgres -d "${DEST_DB}" -c "select count(*) from professors;"

echo "Sync complete."
