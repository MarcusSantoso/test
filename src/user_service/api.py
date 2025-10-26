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
    FriendSchema,
    get_user_repository,
    FriendRequestSchemaV2,
    FriendRequestCreateSchemaV2,
    FriendRequestActionSchemaV2,
    FriendshipSchemaV2,
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


# -------- Friend requests / friendships (Legacy) --------

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





#---------------------------------#
#--- V2 Friends API ---#
#---------------------------------#

@app.get("/v2/users/{user_id}/friends/")
async def list_friends_v2(
    user_id: int,
    repo: UserRepository = Depends(get_user_repository)
):
    """
    List all friends for a user (v2).
    Returns friend data without password hashes.
    """
    try:
        friends = await repo.list_friends_v2(user_id)
        return {"friends": [FriendSchema.from_db_model(f) for f in friends]}
    except LookupError:
        raise HTTPException(status_code=404, detail="User not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing friends: {str(e)}")


@app.get("/v2/users/{user_id}/friends/{friend_identifier}")
async def get_friend_v2(
    user_id: int,
    friend_identifier: str,
    repo: UserRepository = Depends(get_user_repository)
):
    """
    Get a specific friend by name or ID (v2).
    Automatically detects if identifier is numeric (ID) or string (name).
    """
    try:
        # Try to parse as int for ID lookup
        try:
            friend_id = int(friend_identifier)
            friend = await repo.get_friend_by_id_v2(user_id, friend_id)
        except ValueError:
            # Not an int, treat as name
            friend = await repo.get_friend_by_name_v2(user_id, friend_identifier)
        
        if not friend:
            raise HTTPException(status_code=404, detail="Friendship not found")
        
        return {"friend": FriendSchema.from_db_model(friend)}
    
    except LookupError:
        raise HTTPException(status_code=404, detail="User not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving friend: {str(e)}")


@app.delete("/v2/users/{user_id}/friends/{friend_identifier}", status_code=204)
async def delete_friend_v2(
    user_id: int,
    friend_identifier: str,
    repo: UserRepository = Depends(get_user_repository)
):
    """
    Delete a friendship by friend name or ID (v2).
    Removes the friendship for both users.
    """
    try:
        # Try to parse as int for ID lookup
        try:
            friend_id = int(friend_identifier)
            deleted = await repo.delete_friend_by_id_v2(user_id, friend_id)
        except ValueError:
            # Not an int, treat as name
            deleted = await repo.delete_friend_by_name_v2(user_id, friend_identifier)
        
        if not deleted:
            raise HTTPException(status_code=404, detail="Friendship not found")
        
        return Response(status_code=204)
    
    except LookupError:
        raise HTTPException(status_code=404, detail="User not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting friendship: {str(e)}")





#---------------------------------#
#--- V2 Avatar API ---#
#---------------------------------#

@app.get("/v2/users/{user_id}/avatar")
async def get_avatar_v2(
    user_id: int,
    repo: UserRepository = Depends(get_user_repository)
):
    """
    Retrieve a user's profile picture (v2).
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


@app.post("/v2/users/{user_id}/avatar", status_code=201)
async def create_avatar_v2(
    user_id: int,
    file: UploadFile = File(...),
    repo: UserRepository = Depends(get_user_repository)
):
    """
    Create a profile picture for a user (v2).
    Accepts .webp, .png, .jpg files. Images will be cropped to square and resized to 256x256.
    Returns 409 if avatar already exists (use PUT to update).
    """
    # Validate content type
    if file.content_type not in ["image/jpeg", "image/jpg", "image/png", "image/webp"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid image format. Supported formats: JPEG, PNG, WEBP"
        )
    
    try:
        await repo.create_avatar(user_id, file)
        return {"detail": "Avatar created successfully"}
    
    except LookupError:
        raise HTTPException(status_code=404, detail="User not found")
    
    except ValueError as e:
        if "already exists" in str(e):
            raise HTTPException(status_code=409, detail="Avatar already exists. Use PUT to update.")
        raise HTTPException(status_code=400, detail=str(e))
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating avatar: {str(e)}")


@app.put("/v2/users/{user_id}/avatar")
async def update_avatar_v2(
    user_id: int,
    file: UploadFile = File(...),
    repo: UserRepository = Depends(get_user_repository)
):
    """
    Update (or create) a profile picture for a user (v2).
    Accepts .webp, .png, .jpg files. Images will be cropped to square and resized to 256x256.
    """
    # Validate content type
    if file.content_type not in ["image/jpeg", "image/jpg", "image/png", "image/webp"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid image format. Supported formats: JPEG, PNG, WEBP"
        )
    
    try:
        await repo.upload_avatar(user_id, file)
        return {"detail": "Avatar updated successfully"}
    
    except LookupError:
        raise HTTPException(status_code=404, detail="User not found")
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating avatar: {str(e)}")


@app.delete("/v2/users/{user_id}/avatar", status_code=204)
async def delete_avatar_v2(
    user_id: int,
    repo: UserRepository = Depends(get_user_repository)
):
    """
    Delete a user's profile picture (v2).
    Returns 204 No Content on success, 404 if avatar or user not found.
    """
    try:
        await repo.delete_avatar(user_id)
        return Response(status_code=204)
    
    except LookupError:
        raise HTTPException(status_code=404, detail="User not found")
    
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Avatar not found")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting avatar: {str(e)}")
    




#---------------------------------#
#--- V2 Friend Requests API ---#
#---------------------------------#

@app.get("/v2/users/{user_id}/friend-requests/")
async def list_friend_requests_v2(
    user_id: int,
    q: str,  # "incoming" or "outgoing"
    repo: UserRepository = Depends(get_user_repository)
):
    """
    List friend requests for a user (v2).
    Query parameter 'q' must be either 'incoming' or 'outgoing'.
    """
    if q not in ["incoming", "outgoing"]:
        raise HTTPException(
            status_code=400,
            detail="Query parameter 'q' must be 'incoming' or 'outgoing'"
        )
    
    try:
        if q == "incoming":
            requests = await repo.get_incoming_requests_v2(user_id)
        else:  # outgoing
            requests = await repo.get_outgoing_requests_v2(user_id)
        
        # Build response with full user objects
        out: list[FriendRequestSchemaV2] = []
        for req in requests:
            requester = await repo.get_by_id(req.requester_id)
            receiver = await repo.get_by_id(req.receiver_id)
            if requester and receiver:
                out.append(FriendRequestSchemaV2.from_db_model(req, requester, receiver))
        
        return {"requests": out}
    
    except LookupError:
        raise HTTPException(status_code=404, detail="User not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing friend requests: {str(e)}")


@app.post("/v2/users/{user_id}/friend-requests/", status_code=201)
async def create_friend_request_v2(
    user_id: int,
    payload: FriendRequestCreateSchemaV2,
    repo: UserRepository = Depends(get_user_repository)
):
    """
    Create a friend request from user_id to receiver_id (v2).
    """
    try:
        request = await repo.create_friend_request_v2(user_id, payload.receiver_id)
        
        requester = await repo.get_by_id(request.requester_id)
        receiver = await repo.get_by_id(request.receiver_id)
        
        if not requester or not receiver:
            raise HTTPException(status_code=500, detail="Failed to load users for request")
        
        return {"request": FriendRequestSchemaV2.from_db_model(request, requester, receiver)}
    
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating friend request: {str(e)}")


@app.patch("/v2/users/{user_id}/friend-requests/{other_id}")
async def update_friend_request_v2(
    user_id: int,
    other_id: int,
    payload: FriendRequestActionSchemaV2,
    repo: UserRepository = Depends(get_user_repository)
):
    """
    Accept or deny a friend request (v2).
    user_id is the receiver, other_id is the requester.
    Action must be "accept" or "deny".
    """
    if payload.action not in ["accept", "deny"]:
        raise HTTPException(
            status_code=400,
            detail="Action must be 'accept' or 'deny'"
        )
    
    try:
        if payload.action == "accept":
            friendship = await repo.accept_friend_request_v2(user_id, other_id)
            
            first = await repo.get_by_id(friendship.user_id)
            second = await repo.get_by_id(friendship.friend_id)
            
            if not first or not second:
                raise HTTPException(status_code=500, detail="Failed to load friendship users")
            
            return {"friendship": FriendshipSchemaV2.from_users(first, second)}
        
        else:  # deny
            removed = await repo.deny_friend_request_v2(user_id, other_id)
            
            if not removed:
                raise HTTPException(status_code=404, detail="No pending friend request found")
            
            return {"detail": "Friend request denied"}
    
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating friend request: {str(e)}")


@app.delete("/v2/users/{user_id}/friend-requests/{other_id}", status_code=204)
async def delete_friend_request_v2(
    user_id: int,
    other_id: int,
    repo: UserRepository = Depends(get_user_repository)
):
    """
    Delete a friend request (v2).
    Can be called by either the requester (to cancel) or receiver (to reject).
    """
    try:
        deleted = await repo.delete_friend_request_v2(user_id, other_id)
        
        if not deleted:
            raise HTTPException(status_code=404, detail="Friend request not found")
        
        return Response(status_code=204)
    
    except LookupError:
        raise HTTPException(status_code=404, detail="User not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting friend request: {str(e)}")
    




#---------------------------------#
#--- Legacy Avatar API ---#
#---------------------------------#

@app.put("/users/{user_id}/avatar")
async def upload_avatar_legacy(
    user_id: int,
    file: UploadFile = File(...),
    repo: UserRepository = Depends(get_user_repository)
):
    if file.content_type not in ["image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid image format. Supported formats: JPEG, PNG, GIF, WEBP"
        )
    
    try:
        await repo.upload_avatar(user_id, file)
        return {"detail": "Avatar uploaded successfully"}
    
    except LookupError:
        raise HTTPException(status_code=404, detail="User not found")
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading avatar: {str(e)}")


@app.get("/users/{user_id}/avatar")
async def get_avatar_legacy(
    user_id: int,
    repo: UserRepository = Depends(get_user_repository)
):
    try:
        image_bytes, content_type = await repo.get_avatar(user_id)
        return Response(content=image_bytes, media_type=content_type)
    
    except LookupError:
        raise HTTPException(status_code=404, detail="User not found")
    
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Avatar not found")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving avatar: {str(e)}")