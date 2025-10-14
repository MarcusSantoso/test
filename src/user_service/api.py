from fastapi import FastAPI, Depends, Response, HTTPException
from sqlalchemy.exc import IntegrityError
import logging

from admin.main import ui
from .models.user import (
    UserRepository,
    UserSchema,
    UserCreateSchema,
    FriendRequestCreateSchema,
    FriendRequestDecisionSchema,
    FriendRequestSchema,
    FriendshipSchema,
    get_user_repository,
)

logger = logging.getLogger('uvicorn.error')
app = FastAPI()

try:
    ui.run_with(app, mount_path="/admin", favicon="👤", title="User Admin")
except ImportError:
    pass

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


@app.post("/friendships/requests/", status_code=201)
async def create_friend_request(
    payload: FriendRequestCreateSchema,
    user_repo: UserRepository = Depends(get_user_repository),
):
    try:
        request = await user_repo.create_friend_request(
            payload.requester, payload.receiver
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    requester = await user_repo.get_by_id(request.requester_id)
    receiver = await user_repo.get_by_id(request.receiver_id)
    if not requester or not receiver:
        raise HTTPException(status_code=500, detail="Failed to load users for request")

    return {
        "request": FriendRequestSchema.from_db_model(request, requester, receiver)
    }


@app.get("/friendships/requests/{name}")
async def list_friend_requests(
    name: str,
    user_repo: UserRepository = Depends(get_user_repository),
):
    requests = await user_repo.list_friend_requests(name)
    results: list[FriendRequestSchema] = []
    for request in requests:
        requester = await user_repo.get_by_id(request.requester_id)
        receiver = await user_repo.get_by_id(request.receiver_id)
        if requester and receiver:
            results.append(
                FriendRequestSchema.from_db_model(request, requester, receiver)
            )
    return {"requests": results}


@app.post("/friendships/requests/accept")
async def accept_friend_request(
    payload: FriendRequestDecisionSchema,
    user_repo: UserRepository = Depends(get_user_repository),
):
    try:
        friendship = await user_repo.accept_friend_request(
            payload.requester, payload.receiver
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    first = await user_repo.get_by_id(friendship.user_id)
    second = await user_repo.get_by_id(friendship.friend_id)
    if not first or not second:
        raise HTTPException(status_code=500, detail="Failed to load friendship users")
    return {"friendship": FriendshipSchema.from_users(first, second)}


@app.post("/friendships/requests/deny")
async def deny_friend_request(
    payload: FriendRequestDecisionSchema,
    user_repo: UserRepository = Depends(get_user_repository),
):
    try:
        removed = await user_repo.deny_friend_request(
            payload.requester, payload.receiver
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not removed:
        raise HTTPException(status_code=404, detail="No pending friend request found")

    return {"detail": "Friend request denied"}


@app.get("/friendships/{name}")
async def list_friendships(
    name: str,
    user_repo: UserRepository = Depends(get_user_repository),
):
    friendships = await user_repo.list_friendships(name)
    results: list[FriendshipSchema] = []
    for friendship in friendships:
        first = await user_repo.get_by_id(friendship.user_id)
        second = await user_repo.get_by_id(friendship.friend_id)
        if first and second:
            results.append(FriendshipSchema.from_users(first, second))
    return {"friendships": results}

