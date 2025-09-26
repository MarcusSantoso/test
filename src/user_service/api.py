from typing import List
from fastapi import FastAPI, Depends, Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from pydantic import TypeAdapter
import logging

from admin.main import ui
from .models.user import UserRepository, UserSchema, get_user_repository


logger = logging.getLogger('uvicorn.error')
app = FastAPI()

@app.post("/users/", status_code=201)
async def create_user(user: UserSchema, response: Response, user_repo: UserRepository = Depends(get_user_repository)):
    try:
        new_user = await user_repo.create(user.name)
        return {"user": UserSchema.from_db_model(new_user)}
    except IntegrityError as e:
        response.status_code = 409
        return {"detail": "Item already exists"}

@app.get("/users/")
async def list_users(user_repo: UserRepository = Depends(get_user_repository)):

    user_models = await user_repo.get_all()
    users = []
    for model in user_models:
        users.append(UserSchema.from_db_model(model))
    return {'users': users}

@app.get("/users/{name}")
async def get_user(name: str, user_repo: UserRepository = Depends(get_user_repository)):
    user = await user_repo.get_by_name(name)
    return {"user": user}


ui.run_with(app,
            mount_path="/admin",
            favicon="👤",
            title="User Admin")
