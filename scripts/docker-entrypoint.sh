#!/bin/bash

# Retry Alembic migrations a few times to allow the database to become
# available during platform startups (networked DBs can be slow to accept
# connections). This avoids failing the container immediately when the DB is
# still initializing.
MAX_ATTEMPTS=${DB_MIGRATE_RETRIES:-10}
SLEEP_SECONDS=${DB_MIGRATE_SLEEP:-5}

i=0
until alembic upgrade head; do
	i=$((i+1))
	if [ "$i" -ge "$MAX_ATTEMPTS" ]; then
		echo "alembic failed after $i attempts"
		exit 1
	fi
	echo "alembic failed, retrying in ${SLEEP_SECONDS}s (attempt $i/$MAX_ATTEMPTS)"
	sleep $SLEEP_SECONDS
done

exec "$@"
