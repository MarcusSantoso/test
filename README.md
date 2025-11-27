# User Service

Your team has been put in charge of a janky web service that handles user accounts. Nobody knows what the contractors who put this thing together were thinking, but it's up to you and your intrepid teammates to turn this rickety thing into a well-oiled machine that generates tons of shareholder value.

## Getting started

One member from each group will mirror this repository privately on github.com (NOT github.sfu.ca) to create the team repository used for grading. If you wish to follow my recommended git process, then each group member will have their own private fork of the team repository from which they can make pull requests. It may help to create a github organization so your team repository isn't tied to any individual group member's account. All copies of the `user_service` repository must be private. **Making this code and your contributions to it publicly available (i.e., by making your repository public, or by making a pull request against a public repository) constitutes academic dishonesty.**

To mirror, create a private empty repository at `https://github.com/<some_id>/user_service`, and then run:
```
$ git clone https://github.sfu.ca/kjamshid/user_service
$ git remote rename origin source
$ git remote add upstream https://github.com/<some_id>/user_service
$ git push -u main upstream
```

The teaching staff will only be looking at the team repository: it suffices to add kjamsh as a collaborator. Please do not add me as a collaborator to your own repositories, only the team repository.

Project instructions will be posted to the issues page of your team repository on an ongoing basis.

To get a live deployment that you can edit follow these steps.

1. Make a `.env` file containing the following, and DO NOT check it into git:

```
POSTGRES_HOST=db
POSTGRES_USER=<some shared username>
POSTGRES_PASSWORD=<some shared password>
```

2. Launch the application by running:

```
$ docker compose watch
```

The service is now running on `localhost:8000/`.
You can visit `localhost:8000/admin`, `localhost:8000/docs`, and `localhost:8000/redoc` in your browser.

If you edit any of the files in this repo, the server restarts to reflect your changes.

## Environment

This project reads configuration from environment variables. Below are the primary variables teammates should know about when running the app or the test suite.

- `DATABASE_URL` (optional, preferred): Full SQLAlchemy connection string, e.g. `postgresql://postgres:postgres@db:5432/professors_test`. If present the app will try to use this first.
- `REDIS_URL` (required): Redis connection string used by the request/event logging and other features, e.g. `redis://redis:6379/0`.
- `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` (or `DATABASE_USER` / `DATABASE_PASSWORD` / `DATABASE_NAME`): Component variables used to construct a DB URL when `DATABASE_URL` is not provided. Example for Docker/CI: `postgres` / `postgres` / `professors_test`.
- `POSTGRES_HOST` / `DATABASE_HOST` (optional): Hostname for Postgres when constructing a DB URL from components; for compose use `db`.
- `OPENAI_API_KEY` (optional): API key to enable AI summarization. If omitted, summarization features are disabled or will raise when invoked.
- `OPENAI_SUMMARY_MODEL` (optional): Name of the model used by the AI wrapper (default: `gpt-5-mini`).
- `OPENAI_SUMMARY_MAX_WORDS` (optional): Maximum allowed words for generated summaries (optional tuning knob).
- `AUTH_TTL_SECONDS` (optional): TTL used by analytics code; defaults to `300` when unset.

## Local Development: Recommended Workflow

When developing locally you should prefer running the full stack with Docker Compose so every developer runs the same services and the app talks to a reproducible database host name (`db`). This avoids using host-specific addresses like `host.docker.internal` and matches containerized deployments.

- Start the core services:

```bash
docker compose up -d db redis web
```

- Create the database (if needed) and apply migrations from the web container:

```bash
docker compose exec web alembic upgrade head
```

- Recommended `.env` for local Compose-based development (DO NOT commit):

```dotenv
# Use the Compose `db` service as the hostname so containers resolve consistently
POSTGRES_HOST=db
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=user_service
REDIS_URL=redis://redis:6379/0
# Optional: disable remote DATABASE_URL while developing locally
# DATABASE_URL=
```

- Why use `db` (Compose service name):
	- Containers use the Compose internal DNS to resolve `db` to the Postgres container.
	- It is portable for teammates and CI and mirrors production usage where the app uses a single canonical DB host.
	- Avoids platform-specific DNS like `host.docker.internal` which is only for host access and not portable.

- Quick verification:

```bash
# from host: check that the app responds
curl http://127.0.0.1:8000/professors/?limit=1

# inside the db container: check contents
docker compose exec db psql -U ${POSTGRES_USER:-postgres} -d ${POSTGRES_DB:-user_service} -c "select count(*) from professors;"
```


Precedence and notes:
- The code prefers `DATABASE_URL` if present and reachable; if it's unreachable the loader falls back to component vars (`DATABASE_*` or `POSTGRES_*`).
- `REDIS_URL` is required — `get_redis()` will raise if it's missing.
- For local Docker/CI runs, set `POSTGRES_HOST=db` (or set `DATABASE_URL` to use `@db:5432/...`).

Security:
- Do not commit secrets (API keys, DB passwords) into git. Keep a local `.env` file in your development environment that is listed in `.gitignore` and share values via a secure channel.
- If this repository contains a checked-in `.env` with secrets, remove it and rotate any exposed keys immediately.



3. You can follow the logs by running:
```
$ docker compose logs -f [service_name]
```
`service_name` is optional, if you only want to see logs for a given service (one of `web` or `db`).

* You may run into a ResourceExhausted: failed to copy files: userspace copy failed: write /app/.venv/bin/ruff: no space left on device.

```
$ docker system prune --volumes
```


* You can run tests as follows:
```
$ docker compose exec web pytest
```

## Relevant documentation

[FastAPI User Guide](https://fastapi.tiangolo.com/tutorial/first-steps/) - This is the main library our web service runs on. Note that wherever it says to run, e.g., `fastapi dev main.py`, you should run `docker compose watch` to get a live server.

[SQLAlchemy](https://docs.sqlalchemy.org/en/20/orm/quickstart.html) - This is the library we use to access our database (which is PostgreSQL). Use the links in the table of contents to skip to the type of query you want.

[Alembic](https://alembic.sqlalchemy.org/en/latest/) - This tool is used to manage changes to our database schemas. Whenever you want to modify a table's shape in postgres (i.e., add, remove, or change the type of a column), use an alembic migration.

[NiceGUI](https://nicegui.io/) - This is the library used for the frontend in the admin interface.

## SFU sync CLI

The project includes a small sync helper that pulls instructor lists from
Simon Fraser University's Course Outlines API and (optionally) scrapes
RateMyProfessors/Reddit for reviews.

- Run the sync in dry-run mode (won't modify your Postgres DB):

```bash
python3 -m src.services.sfu_sync --department CMPT --recent-terms 1 --max-courses 10
```

- If your environment does not have the `DATABASE_*` variables set and you
	run the sync without `--commit` it will automatically fall back to an
	in-memory SQLite database so you can test safely. When `--commit` is
	provided the CLI requires a real DB (and will error if `get_db()` fails).

- To persist results to your Postgres DB, set the DB env vars and pass
	`--commit`:

```bash
export DATABASE_HOST=... DATABASE_USER=... DATABASE_PASSWORD=... DATABASE_NAME=...
python3 -m src.services.sfu_sync --department CMPT --recent-terms 2 --max-courses 100 --commit
```

The `sfu_sync` CLI is handy for testing and small imports. It's a good idea
to run it in dry-run mode first and inspect results before committing.

## Developer DB snapshot and restore

When you want teammates to run the same local database (schema + sample data),
follow this recommended flow:

1. Ensure schema changes are captured as Alembic migrations. To apply migrations
	 from the web container run:

```
docker compose exec web alembic upgrade head
```

2. We include a small sanitized SQL sample file at `data/user_service_sample.sql`.
	 To start DB + Adminer and restore the sample data use the Makefile targets:

```
make db-up
make db-restore-sample
```

3. Alternatively restore the SQL file manually:

```
docker compose up -d db adminer
docker cp data/user_service_sample.sql user_service-db-1:/tmp/user_service_sample.sql
docker compose exec db psql -U postgres -d user_service -f /tmp/user_service_sample.sql
```

4. If you have a real dump file (`.dump`) use `pg_restore` instead of `psql`:

```
# copy into container
docker cp user_service_dev.dump user_service-db-1:/tmp/user_service_dev.dump
docker compose exec db pg_restore -U postgres -d user_service /tmp/user_service_dev.dump
```

Notes:
- Do NOT commit production database dumps into the repo. Use sanitized sample
	data for developer onboarding.
- Always commit Alembic migration files alongside code that requires schema
	changes so teammates can run `alembic upgrade head` to get the right schema.


## How to run tests (local and in Docker)

Below are the recommended steps teammates should follow to run the test suite. The Docker-based flow matches CI and is preferred when validating changes before a PR.

Prerequisites:
- Docker + Docker Compose plugin
- Python 3.13 (for local venv runs)

1) Quick local test run (using a Python venv):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
pytest -q
```

2) Recommended: CI-like Docker test run (matches what CI executes):

Set sensible defaults (zsh/mac):

```bash
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD=postgres
export POSTGRES_DB=professors_test
export REDIS_URL=redis://redis:6379/0
```

Start Postgres and Redis:

```bash
docker compose up -d db redis
```

Create the test DB inside the Postgres container if it does not already exist:

```bash
docker compose exec db bash -lc "createdb -U ${POSTGRES_USER:-postgres} ${POSTGRES_DB} || true"
```

Run the tests inside the `web` container with the `DATABASE_URL` forced to use the compose `db` host:

```bash
docker compose run --rm \
	-e DATABASE_URL=postgresql://postgres:postgres@db:5432/${POSTGRES_DB} \
	-e REDIS_URL=redis://redis:6379/0 \
	web pytest -q
```

Expected: tests should pass (example from local run: `132 passed, 1 warning`).

3) One-line Makefile helper (available in this repo):

You can also use the Makefile targets we added to automate DB creation and the docker test run:

```bash
export POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres POSTGRES_DB=professors_test
make docker-test
```

Notes:
- If you see failures during Alembic migrations, confirm `POSTGRES_DB` exists in the running Postgres container (the `create-test-db` Makefile target runs `createdb` to help with this).
- For CI, ensure your pipeline creates the DB and/or sets `DATABASE_URL` to point to the test DB used by the job.

