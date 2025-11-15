import asyncio
import json
from datetime import datetime

import pytest

import httpx

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.user_service.models.user import Base
from src.user_service.models import Professor, Review
from src.services.scraper_service import scrape_professor_by_id


class FakeResponse:
    def __init__(self, status_code=200, text="", data=None):
        self.status_code = status_code
        self._text = text
        self._data = data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    @property
    def text(self):
        return self._text

    def json(self):
        return self._data


class FakeClient:
    def __init__(self, *args, **kwargs):
        # store call sequence to return appropriate responses
        self._calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, *args, **kwargs):
        # Determine response by URL pattern
        if "reddit.com/search.json" in url:
            # Return a JSON with one child
            now_ts = int(datetime.now().timestamp())
            data = {"data": {"children": [{"data": {"title": "Great lecture by Prof", "selftext": "Very clear", "created_utc": now_ts}}]}}
            return FakeResponse(200, text=json.dumps(data), data=data)

        if "ratemyprofessors.com/search/teachers" in url:
            # Return HTML containing a ShowRatings.jsp?tid=123 link
            html = '<a href="/ShowRatings.jsp?tid=123">Professor</a>'
            return FakeResponse(200, text=html)

        if "ShowRatings.jsp?tid=123" in url or "ShowRatings.jsp?tid=" in url:
            # Return a professor page with a review block matching our simplistic regex
            page = '<div class="Rating__RatingBody"><p>Excellent instructor</p></div>'
            return FakeResponse(200, text=page)

        # default empty
        return FakeResponse(200, text="")


def get_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def test_scrape_reddit_and_store(monkeypatch):
    db = get_session()
    # create professor
    prof = Professor(name="Dr Test Reddit", department="CS")
    db.add(prof)
    db.commit()
    db.refresh(prof)

    # patch httpx.Client to our fake
    monkeypatch.setattr(httpx, "Client", FakeClient)

    added = scrape_professor_by_id(db, prof.id)
    assert added >= 1

    # calling again should not create duplicates
    added2 = scrape_professor_by_id(db, prof.id)
    assert added2 == 0


def test_scrape_rmp_and_store(monkeypatch):
    db = get_session()
    prof = Professor(name="Dr Test RMP", department="Math")
    db.add(prof)
    db.commit()
    db.refresh(prof)

    monkeypatch.setattr(httpx, "Client", FakeClient)

    added = scrape_professor_by_id(db, prof.id)
    # RMP scraping may return one review from our fake client
    assert added >= 1

    # ensure Review row contains expected source
    rev = db.query(Review).filter(Review.prof_id == prof.id).first()
    assert rev is not None
    assert rev.source in ("reddit", "ratemyprofessors")
