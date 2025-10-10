from typing import List
from fastapi import FastAPI, Depends, Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from pydantic import TypeAdapter
import logging

from admin.main import ui
from .models.user import UserRepository, UserSchema, UserCreateSchema, get_user_repository

logger = logging.getLogger('uvicorn.error')
app = FastAPI()

@app.post("/users/", status_code=201)
async def create_user(user: UserCreateSchema, response: Response, user_repo: UserRepository = Depends(get_user_repository)):
    """
    Accept dict with name, email, password. Only return name and id in API.
    """
    try:
        new_user = await user_repo.create(user.name, user.email, user.password)
        return {"user": UserSchema.from_db_model(new_user)}
    except IntegrityError:
        response.status_code = 409
        return {"detail": "Item already exists"}

@app.post("/users/delete")
async def delete_user(user: UserSchema, response: Response, user_repo: UserRepository = Depends(get_user_repository)):
    was_deleted = await user_repo.delete(user.name)
    if not was_deleted:
        response.status_code = 404
        return {"detail": "User not found"}
    return {"detail": "User deleted"}

@app.get("/users/")
async def list_users(user_repo: UserRepository = Depends(get_user_repository)):
    user_models = await user_repo.get_all()
    return {"users": [UserSchema.from_db_model(u) for u in user_models]}

@app.get("/users/{name}")
async def get_user(name: str, user_repo: UserRepository = Depends(get_user_repository)):
    user = await user_repo.get_by_name(name)
    if not user:
        return {"user": None}
    return {"user": UserSchema.from_db_model(user)}

if __name__ == "__main__":
    try:
        from admin.main import ui
        ui.run_with(app, mount_path="/admin", favicon="👤", title="User Admin")
    except ImportError:
        pass