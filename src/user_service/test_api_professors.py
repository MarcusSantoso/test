import os
import tempfile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure REDIS_URL is set so the request-event logger doesn't raise during tests
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from src.user_service.api import app
from src.user_service.models.user import Base
from src.user_service.models import Review, AISummary
from src.shared.database import get_db


def test_create_and_get_professor_with_relations():
    # create a temporary file-backed SQLite DB so connections share the same DB
    tf = tempfile.NamedTemporaryFile(prefix="test_prof_db", suffix=".db", delete=False)
    tf.close()
    db_path = tf.name
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # create tables
    Base.metadata.create_all(bind=engine)

    # dependency override
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    # create professor via API
    resp = client.post("/professors/", json={"name": "Dr Test", "department": "CS", "rmp_url": "http://rmp/test"})
    assert resp.status_code == 201
    prof = resp.json()["professor"]
    prof_id = prof["id"]

    # insert a review and an AI summary directly using the same session factory
    db = TestingSessionLocal()
    try:
        review = Review(prof_id=prof_id, text="Excellent", source="rmp", rating=5)
        summary = AISummary(prof_id=prof_id, pros=["Clear lectures"], cons=[], neutral=[], updated_at=None)
        db.add(review)
        db.add(summary)
        db.commit()
    finally:
        db.close()

    # fetch professor and ensure relationships are present
    resp2 = client.get(f"/professors/{prof_id}")
    assert resp2.status_code == 200
    body = resp2.json()["professor"]
    assert body["id"] == prof_id
    assert isinstance(body.get("reviews"), list) and len(body["reviews"]) == 1
    assert body["reviews"][0]["text"] == "Excellent"
    assert body.get("ai_summary") is not None
    assert body["ai_summary"]["pros"] == ["Clear lectures"]

    # cleanup override and remove temp DB file
    app.dependency_overrides.pop(get_db, None)
    try:
        os.unlink(db_path)
    except Exception:
        pass
