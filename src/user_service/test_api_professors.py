import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure REDIS_URL is set so the request-event logger doesn't raise during tests
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from src.user_service.api import app, _resolve_ai_engine
from src.user_service.models.user import Base
from src.user_service.models import Review, AISummary
from src.shared.database import get_db


@pytest.fixture()
def temp_db_client(tmp_path):
    db_path = tmp_path / "professors.db"
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
    yield client, TestingSessionLocal

    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def test_create_and_get_professor_with_relations(temp_db_client):
    client, TestingSessionLocal = temp_db_client

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


class DummyStructuredEngine:
    def __init__(self):
        self.model = "dummy-structure"
        self.calls = 0

    async def summarize_with_raw(self, text, *, options=None):
        self.calls += 1
        payload = {
            "pros": [f"pro-{self.calls}"],
            "cons": [f"con-{self.calls}"],
            "neutral": [f"neutral-{self.calls}"],
        }
        return json.dumps(payload), "{}"


def _override_engine(dummy):
    def _provider():
        return dummy

    return _provider


def test_professor_summary_refresh_and_auto_refresh(temp_db_client):
    client, TestingSessionLocal = temp_db_client
    dummy = DummyStructuredEngine()
    app.dependency_overrides[_resolve_ai_engine] = _override_engine(dummy)

    resp = client.post("/professors/", json={"name": "Dr Summary"})
    prof_id = resp.json()["professor"]["id"]

    db = TestingSessionLocal()
    try:
        for idx in range(3):
            db.add(Review(prof_id=prof_id, text=f"Great {idx}", rating=5 - idx, source="rmp"))
        db.commit()
    finally:
        db.close()

    resp_summary = client.get(f"/prof/{prof_id}/summary")
    assert resp_summary.status_code == 200
    payload = resp_summary.json()["summary"]
    assert payload["pros"] == ["pro-1"]
    assert dummy.calls == 1

    db = TestingSessionLocal()
    try:
        for idx in range(2):
            db.add(Review(prof_id=prof_id, text=f"New {idx}", rating=3, source="forum"))
        db.commit()
    finally:
        db.close()

    resp_summary_2 = client.get(f"/prof/{prof_id}/summary")
    assert resp_summary_2.status_code == 200
    assert dummy.calls == 1  # not enough new reviews yet

    db = TestingSessionLocal()
    try:
        db.add(Review(prof_id=prof_id, text="Another new review", rating=4, source="email"))
        db.commit()
    finally:
        db.close()

    resp_summary_3 = client.get(f"/prof/{prof_id}/summary")
    assert resp_summary_3.status_code == 200
    assert dummy.calls == 2  # auto refreshed after 3rd new review

    force_resp = client.post(f"/prof/{prof_id}/summary/refresh")
    assert force_resp.status_code == 200
    assert dummy.calls == 3

    app.dependency_overrides.pop(_resolve_ai_engine, None)


def test_professor_summary_requires_reviews(temp_db_client):
    client, _ = temp_db_client
    dummy = DummyStructuredEngine()
    app.dependency_overrides[_resolve_ai_engine] = _override_engine(dummy)

    resp = client.post("/professors/", json={"name": "Dr Empty"})
    prof_id = resp.json()["professor"]["id"]

    resp_summary = client.get(f"/prof/{prof_id}/summary")
    assert resp_summary.status_code == 400

    resp_force = client.post(f"/prof/{prof_id}/summary/refresh")
    assert resp_force.status_code == 400

    app.dependency_overrides.pop(_resolve_ai_engine, None)
