## Makefile - convenience tasks for local development

.PHONY: db-up db-restore-sample db-seed migrate

db-up:
	@echo "Starting DB and Adminer via docker-compose..."
	docker compose up -d db adminer

db-restore-sample: db-up
	@echo "Copying and restoring sample DB into docker Postgres (user_service)..."
	docker cp data/user_service_sample.sql user_service-db-1:/tmp/user_service_sample.sql
	docker compose exec db psql -U postgres -d user_service -f /tmp/user_service_sample.sql

db-seed: db-restore-sample
	@echo "Sample data restored into local Postgres. Use Adminer at http://127.0.0.1:8080 to inspect."

migrate:
	@echo "Run alembic migrations (from web container to ensure environment matches)"
	docker compose exec web alembic upgrade head

# Convenience aliases matching colon-style targets some teams prefer
.PHONY: db:up db:restore
db:up: db-up

db:restore: db-restore-sample

