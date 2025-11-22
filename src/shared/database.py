from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
import os
from dotenv import load_dotenv

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
            engine = create_engine(database_url)
            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        else:
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

            if not host or not username or not password:
                raise RuntimeError(
                    "Database connection requires env vars: DATABASE_URL or (DATABASE_HOST, DATABASE_USER, DATABASE_PASSWORD)"
                )

            DATABASE_URL = f"postgresql+psycopg2://{username}:{password}@{host}:{port}/{db_name}"
            engine = create_engine(DATABASE_URL)
            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
