from fastapi import FastAPI
from event_service.router import router as event_router
from event_service.models import Base
from shared.database import get_db

app = FastAPI(title="User Engagement Analytics API", version="2.0")

# Create tables at startup
with next(get_db()) as db:
    Base.metadata.create_all(bind=db.get_bind())

app.include_router(event_router)

@app.get("/")
def root():
    return {"message": "Analytics API v2 is running 🚀"}
