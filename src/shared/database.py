from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
import os
from dotenv import load_dotenv

load_dotenv()  # make sure environment variables are loaded

engine = None
SessionLocal = None

def get_db():
    """Yield a SQLAlchemy session using lazy engine initialization."""
    global engine, SessionLocal

    if not engine:
        host = os.environ["DATABASE_HOST"]
        username = os.environ["DATABASE_USER"]
        password = os.environ["DATABASE_PASSWORD"]
        db_name = (
            os.environ.get("DATABASE_NAME")
            or os.environ.get("POSTGRES_DB")
            or username
            or "postgres"
        )

        DATABASE_URL = f"postgresql+psycopg2://{username}:{password}@{host}:5432/{db_name}"
        engine = create_engine(DATABASE_URL)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
