import asyncio
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Import the models package so all model modules register with Base.metadata
import src.user_service.models  # noqa: F401

from src.user_service.models.user import Base
from src.user_service.models import Professor, Review, AISummary


def get_repo():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    session = Session(engine)
    Base.metadata.create_all(engine)
    return session


def test_professor_review_and_summary_relationships():
    session = get_repo()

    async def runner():
        # create a professor
        prof = Professor(name="Dr Test", department="Testing", rmp_url="http://rmp/test")
        session.add(prof)
        session.commit()
        session.refresh(prof)

        # add a review
        rev = Review(prof_id=prof.id, text="Great teacher", source="rmp", rating=5)
        session.add(rev)

        # add ai summary
        summ = AISummary(prof_id=prof.id, pros=["clear"], cons=["none"], neutral=[], updated_at=None)
        session.add(summ)
        session.commit()

        # reload professor and assert relationships
        loaded = session.get(Professor, prof.id)
        assert loaded is not None
        # reviews relationship should include our review
        assert hasattr(loaded, "reviews")
        assert len(loaded.reviews) == 1
        assert loaded.reviews[0].text == "Great teacher"
        # ai_summary should be accessible
        assert getattr(loaded, "ai_summary") is not None
        assert loaded.ai_summary.pros == ["clear"]

    asyncio.run(runner())
    session.close()
