from typing import List
from fastapi import FastAPI, Depends, Response, HTTPException, UploadFile, File
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

logger = logging.getLogger("uvicorn.error")
app = FastAPI()

try:
    ui.run_with(app, mount_path="/admin", favicon="👤", title="User Admin")
except Exception:
    pass


@app.post("/users/", status_code=201)
async def create_user(
    user: UserCreateSchema,
    response: Response,
    user_repo: UserRepository = Depends(get_user_repository),
):
    """Accept name/email/password; return only {name,id}."""
    try:
        new_user = await user_repo.create(user.name, user.email, user.password)
        return {"user": UserSchema.from_db_model(new_user)}
    except IntegrityError:
        response.status_code = 409
        return {"detail": "Item already exists"}


@app.post("/users/delete")
async def delete_user(
    user: UserSchema,
    response: Response,
    user_repo: UserRepository = Depends(get_user_repository),
):
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


# -------- Friend requests / friendships --------

@app.post("/friendships/requests/", status_code=201)
async def create_friend_request(
    payload: FriendRequestCreateSchema,
    user_repo: UserRepository = Depends(get_user_repository),
):
    try:
        request = await user_repo.create_friend_request(payload.requester, payload.receiver)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    requester = await user_repo.get_by_id(request.requester_id)
    receiver = await user_repo.get_by_id(request.receiver_id)
    if not requester or not receiver:
        raise HTTPException(status_code=500, detail="Failed to load users for request")

    return {"request": FriendRequestSchema.from_db_model(request, requester, receiver)}


@app.get("/friendships/requests/{name}")
async def list_friend_requests(
    name: str, user_repo: UserRepository = Depends(get_user_repository)
):
    requests = await user_repo.list_friend_requests(name)
    out: list[FriendRequestSchema] = []
    for req in requests:
        requester = await user_repo.get_by_id(req.requester_id)
        receiver = await user_repo.get_by_id(req.receiver_id)
        if requester and receiver:
            out.append(FriendRequestSchema.from_db_model(req, requester, receiver))
    return {"requests": out}


@app.post("/friendships/requests/accept")
async def accept_friend_request(
    payload: FriendRequestDecisionSchema,
    user_repo: UserRepository = Depends(get_user_repository),
):
    try:
        friendship = await user_repo.accept_friend_request(payload.requester, payload.receiver)
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
        removed = await user_repo.deny_friend_request(payload.requester, payload.receiver)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not removed:
        raise HTTPException(status_code=404, detail="No pending friend request found")
    return {"detail": "Friend request denied"}


@app.get("/friendships/{name}")
async def list_friendships(
    name: str, user_repo: UserRepository = Depends(get_user_repository)
):
    friendships = await user_repo.list_friendships(name)
    out: list[FriendshipSchema] = []
    for fr in friendships:
        first = await user_repo.get_by_id(fr.user_id)
        second = await user_repo.get_by_id(fr.friend_id)
        if first and second:
            out.append(FriendshipSchema.from_users(first, second))
    return {"friendships": out}


@app.put("/users/{user_id}/avatar")
async def upload_avatar(
    user_id: int,
    file: UploadFile = File(...),
    repo: UserRepository = Depends(get_user_repository)
):

    if file.content_type not in ["image/jpeg", "image/jpg", "image/png", "image/gif"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid image format. Supported formats: JPEG, PNG, GIF"
        )
    
    try:
        await repo.upload_avatar(user_id, file)
        return {"detail": "Avatar uploaded successfully"}
    
    except LookupError as e:
        raise HTTPException(status_code=404, detail="User not found")
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading avatar: {str(e)}")


@app.get("/users/{user_id}/avatar")
async def get_avatar(
    user_id: int,
    repo: UserRepository = Depends(get_user_repository)
):
    """
    Retrieve a user's profile picture.
    """
    try:
        image_bytes, content_type = await repo.get_avatar(user_id)
        return Response(content=image_bytes, media_type=content_type)
    
    except LookupError:
        raise HTTPException(status_code=404, detail="User not found")
    
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Avatar not found")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving avatar: {str(e)}")