from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
import os
from dotenv import load_dotenv
import logging

load_dotenv()  # make sure environment variables are loaded

engine = None
SessionLocal = None

def get_db():
    """Yield a SQLAlchemy session using lazy engine initialization.

    This helper will read `DATABASE_HOST`, `DATABASE_USER`, `DATABASE_PASSWORD`,
    and optionally `DATABASE_NAME`. For convenience it also accepts the older
    `POSTGRES_HOST`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` env
    variables as fallbacks.
    """
    global engine, SessionLocal

    if not engine:
        # If a full DATABASE_URL is provided, prefer it (12factor style).
        database_url = os.environ.get("DATABASE_URL")
        if database_url:
            # Try to use the provided DATABASE_URL but be tolerant: if the host
            # in DATABASE_URL is not reachable (e.g. a remote host not resolvable
            # from this environment), fall back to constructing a local Postgres
            # URL from POSTGRES_* / DATABASE_* env vars or localhost defaults.
            try:
                # use a short connect timeout for quicker failure when host unreachable
                engine = create_engine(database_url, connect_args={"connect_timeout": 3})
                # attempt a quick connect to validate reachability
                with engine.connect() as _conn:
                    pass
                SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            except Exception as exc:
                logging.warning("DATABASE_URL provided but connection failed (%s). Falling back to POSTGRES_*/localhost. Error: %s", database_url, exc)
                # clear engine/session so we build from components below
                engine = None
                SessionLocal = None

        # If we couldn't build an engine from DATABASE_URL (or none provided),
        # construct a URL from component env vars and sensible localhost defaults.
        if not SessionLocal:
            # Build URL from components, prefer DATABASE_* but accept POSTGRES_* fallbacks
            host = os.environ.get("DATABASE_HOST") or os.environ.get("POSTGRES_HOST")
            port = os.environ.get("DATABASE_PORT") or os.environ.get("POSTGRES_PORT") or "5432"
            username = os.environ.get("DATABASE_USER") or os.environ.get("POSTGRES_USER")
            password = os.environ.get("DATABASE_PASSWORD") or os.environ.get("POSTGRES_PASSWORD")
            db_name = (
                os.environ.get("DATABASE_NAME")
                or os.environ.get("POSTGRES_DB")
                or username
                or "postgres"
            )
            # If a host wasn't provided, default to localhost so dev setups
            # using docker-compose / Adminer (127.0.0.1) work without extra env.
            if not host:
                host = "127.0.0.1"

            # Provide sensible defaults for local development if credentials
            # are not set; prefer explicit env vars otherwise.
            if not username:
                username = os.environ.get("POSTGRES_USER") or os.environ.get("DATABASE_USER") or "postgres"
            if not password:
                password = os.environ.get("POSTGRES_PASSWORD") or os.environ.get("DATABASE_PASSWORD") or "postgres"

            # Build final URL and create engine
            DATABASE_URL = f"postgresql+psycopg2://{username}:{password}@{host}:{port}/{db_name}"
            engine = create_engine(DATABASE_URL)
            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
