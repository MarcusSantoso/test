from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, EmailStr
from datetime import datetime
from sqlalchemy import (
    String,
    Integer,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
    select,
    insert,
    delete,
    and_,
    or_,
)
from sqlalchemy.orm import declarative_base, Session, mapped_column, Mapped
from fastapi import Depends, UploadFile
from PIL import Image
import io
from pathlib import Path

from src.shared.database import get_db

Base = declarative_base()

AVATAR_MAX_SIZE = 256
AVATAR_DIR = Path("avatars")
AVATAR_DIR.mkdir(exist_ok=True)


# -------------------- Models --------------------

class User(Base):
    """
    Minimal user model that matches the tests:
      - id (int pk autoincrement)
      - name (unique, not null)
      - email (not null)
      - password (not null)  <-- tests insert into this column directly
    You can add more fields later, but they must be nullable or have defaults
    so raw INSERTs in the tests don't fail.
    """
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("name", name="uq_users_name"),
        UniqueConstraint("email", name="uq_users_email"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    password: Mapped[str] = mapped_column(String, nullable=False)
    # subscription tier (1 = lowest). Default to 1 so existing tests that
    # insert raw rows continue to work.
    tier: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # server-side token invalidation: tokens issued before this UTC timestamp
    # are considered invalid. Nullable (no invalidation).
    jwt_valid_after: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FriendRequest(Base):
    """A pending friend request between two users."""
    __tablename__ = "friend_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    requester_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    receiver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "requester_id", "receiver_id", name="uq_friend_requests_requester_receiver"
        ),
    )


class Friendship(Base):
    """
    Confirmed friendship between two users, stored once with (lower_id, higher_id).
    """
    __tablename__ = "friendships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    friend_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "friend_id", name="uq_friendships_user_friend"),
        CheckConstraint("user_id < friend_id", name="ck_friendships_user_less_friend"),
    )


# -------------------- Repository --------------------

class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    async def create(self, name: str, email: str, password: str) -> User:
        result = self.session.execute(
            insert(User)
            .values(name=name, email=email, password=password)
            .returning(User)
        )
        user = result.scalar_one()
        self.session.commit()
        return user

    async def delete(self, name: str) -> bool:
        # Ensure referential cleanup for databases (like SQLite tests)
        # that may not have foreign key ON DELETE CASCADE enabled.
        user = await self.get_by_name(name)
        if not user:
            return False

        # Delete any pending friend requests involving this user
        self.session.execute(
            delete(FriendRequest).where(
                or_(FriendRequest.requester_id == user.id, FriendRequest.receiver_id == user.id)
            )
        )

        # Delete any friendships involving this user
        self.session.execute(
            delete(Friendship).where(
                or_(Friendship.user_id == user.id, Friendship.friend_id == user.id)
            )
        )

        # Finally delete the user record
        result = self.session.execute(delete(User).where(User.name == name))
        self.session.commit()
        return result.rowcount > 0

    async def get_all(self) -> list[User]:
        return self.session.scalars(select(User)).all()

    async def get_many(
        self, limit: int = 100, offset: int = 0, search: str | None = None
    ) -> list[User]:
        stmt = select(User)
        if search:
            stmt = stmt.where(User.name.ilike(f"%{search}%"))
        stmt = stmt.order_by(User.name).limit(limit).offset(offset)
        return self.session.scalars(stmt).all()

    async def count(self, search: str | None = None) -> int:
        from sqlalchemy import func
        stmt = select(func.count()).select_from(User)
        if search:
            stmt = stmt.where(User.name.ilike(f"%{search}%"))
        return int(self.session.scalar(stmt) or 0)

    async def get_by_name(self, name: str) -> Optional[User]:
        return self.session.scalars(select(User).where(User.name == name).limit(1)).first()

    async def get_by_id(self, user_id: int) -> Optional[User]:
        return self.session.get(User, user_id)

    # ---- Friend request / friendship helpers used by tests ----

    async def create_friend_request(self, requester_name: str, receiver_name: str) -> FriendRequest:
        if requester_name == receiver_name:
            raise ValueError("Cannot send a friend request to yourself")

        requester = await self.get_by_name(requester_name)
        receiver = await self.get_by_name(receiver_name)
        if not requester or not receiver:
            raise LookupError("Both users must exist")

        existing = self.session.scalar(
            select(FriendRequest).where(
                or_(
                    and_(
                        FriendRequest.requester_id == requester.id,
                        FriendRequest.receiver_id == receiver.id,
                    ),
                    and_(
                        FriendRequest.requester_id == receiver.id,
                        FriendRequest.receiver_id == requester.id,
                    ),
                )
            )
        )
        if existing:
            raise ValueError("A friend request already exists between these users")

        result = self.session.execute(
            insert(FriendRequest)
            .values(requester_id=requester.id, receiver_id=receiver.id)
            .returning(FriendRequest)
        )
        req = result.scalar_one()
        self.session.commit()
        return req

    async def accept_friend_request(self, requester_name: str, receiver_name: str) -> "Friendship":
        if requester_name == receiver_name:
            raise ValueError("Cannot accept a request from yourself")

        requester = await self.get_by_name(requester_name)
        receiver = await self.get_by_name(receiver_name)
        if not requester or not receiver:
            raise LookupError("Both users must exist")

        pending = self.session.scalar(
            select(FriendRequest).where(
                and_(
                    FriendRequest.requester_id == requester.id,
                    FriendRequest.receiver_id == receiver.id,
                )
            )
        )
        if not pending:
            raise LookupError("No pending friend request found")

        a, b = self._normalize_pair(requester.id, receiver.id)

        already = self.session.scalar(
            select(Friendship).where(and_(Friendship.user_id == a, Friendship.friend_id == b))
        )
        if already:
            self.session.execute(delete(FriendRequest).where(FriendRequest.id == pending.id))
            self.session.commit()
            raise ValueError("Users are already friends")

        result = self.session.execute(
            insert(Friendship).values(user_id=a, friend_id=b).returning(Friendship)
        )
        friendship = result.scalar_one()
        self.session.execute(delete(FriendRequest).where(FriendRequest.id == pending.id))
        self.session.commit()
        return friendship

    async def deny_friend_request(self, requester_name: str, receiver_name: str) -> bool:
        requester = await self.get_by_name(requester_name)
        receiver = await self.get_by_name(receiver_name)
        if not requester or not receiver:
            raise LookupError("Both users must exist")

        result = self.session.execute(
            delete(FriendRequest).where(
                and_(
                    FriendRequest.requester_id == requester.id,
                    FriendRequest.receiver_id == receiver.id,
                )
            )
        )
        self.session.commit()
        return result.rowcount > 0

    async def list_friend_requests(self, name: str) -> list[FriendRequest]:
        user = await self.get_by_name(name)
        if not user:
            return []
        stmt = select(FriendRequest).where(
            or_(FriendRequest.requester_id == user.id, FriendRequest.receiver_id == user.id)
        )
        return self.session.scalars(stmt).all()

    async def list_all_friend_requests(self) -> list[FriendRequest]:
        return self.session.scalars(select(FriendRequest)).all()

    async def list_friendships(self, name: str) -> list[Friendship]:
        user = await self.get_by_name(name)
        if not user:
            return []
        stmt = select(Friendship).where(
            or_(Friendship.user_id == user.id, Friendship.friend_id == user.id)
        )
        return self.session.scalars(stmt).all()

    async def are_friends(self, first_name: str, second_name: str) -> bool:
        first = await self.get_by_name(first_name)
        second = await self.get_by_name(second_name)
        if not first or not second:
            return False
        return await self.are_friends_by_ids(first.id, second.id)

    async def are_friends_by_ids(self, first_id: int, second_id: int) -> bool:
        a, b = self._normalize_pair(first_id, second_id)
        return self.session.scalar(
            select(Friendship).where(and_(Friendship.user_id == a, Friendship.friend_id == b))
        ) is not None

    @staticmethod
    def _normalize_pair(first: int, second: int) -> tuple[int, int]:
        return (first, second) if first < second else (second, first)
    
    # ---- V2 Friends API methods ----
    
    async def list_friends_v2(self, user_id: int) -> list[User]:
        """
        List all friends for a user.
        Returns User objects without password hashes (handled by schema).
        """
        user = await self.get_by_id(user_id)
        if not user:
            raise LookupError("User not found")
        
        # Get all friendships where user is either user_id or friend_id
        friendships = await self.list_friendships_by_id(user_id)
        
        friend_ids = []
        for friendship in friendships:
            if friendship.user_id == user_id:
                friend_ids.append(friendship.friend_id)
            else:
                friend_ids.append(friendship.user_id)
        
        # Fetch all friend User objects
        friends = []
        for friend_id in friend_ids:
            friend = await self.get_by_id(friend_id)
            if friend:
                friends.append(friend)
        
        return friends
    
    async def list_friendships_by_id(self, user_id: int) -> list[Friendship]:
        """Get all friendships for a user by ID."""
        stmt = select(Friendship).where(
            or_(Friendship.user_id == user_id, Friendship.friend_id == user_id)
        )
        return self.session.scalars(stmt).all()
    
    async def get_friend_by_name_v2(self, user_id: int, friend_name: str) -> Optional[User]:
        """
        Get a specific friend by name.
        Returns the friend User object if they are friends, None otherwise.
        """
        user = await self.get_by_id(user_id)
        if not user:
            raise LookupError("User not found")
        
        # Prevent getting self as friend
        if user.name == friend_name:
            return None
        
        friend = await self.get_by_name(friend_name)
        if not friend:
            return None
        
        # Check if they are friends
        if await self.are_friends_by_ids(user_id, friend.id):
            return friend
        
        return None
    
    async def get_friend_by_id_v2(self, user_id: int, friend_id: int) -> Optional[User]:
        """
        Get a specific friend by ID.
        Returns the friend User object if they are friends, None otherwise.
        """
        user = await self.get_by_id(user_id)
        if not user:
            raise LookupError("User not found")
        
        # Prevent getting self as friend
        if user_id == friend_id:
            return None
        
        friend = await self.get_by_id(friend_id)
        if not friend:
            return None
        
        # Check if they are friends
        if await self.are_friends_by_ids(user_id, friend_id):
            return friend
        
        return None
    
    async def delete_friend_by_name_v2(self, user_id: int, friend_name: str) -> bool:
        """
        Delete a friendship by friend name.
        Returns True if friendship was deleted, False if not found.
        """
        user = await self.get_by_id(user_id)
        if not user:
            raise LookupError("User not found")
        
        friend = await self.get_by_name(friend_name)
        if not friend:
            return False
        
        return await self.delete_friendship_by_ids(user_id, friend.id)
    
    async def delete_friend_by_id_v2(self, user_id: int, friend_id: int) -> bool:
        """
        Delete a friendship by friend ID.
        Returns True if friendship was deleted, False if not found.
        """
        user = await self.get_by_id(user_id)
        if not user:
            raise LookupError("User not found")
        
        friend = await self.get_by_id(friend_id)
        if not friend:
            return False
        
        return await self.delete_friendship_by_ids(user_id, friend_id)
    
    async def delete_friendship_by_ids(self, user_id: int, friend_id: int) -> bool:
        """
        Delete a friendship between two users.
        Returns True if deleted, False if not found.
        """
        a, b = self._normalize_pair(user_id, friend_id)
        
        result = self.session.execute(
            delete(Friendship).where(
                and_(Friendship.user_id == a, Friendship.friend_id == b)
            )
        )
        self.session.commit()
        return result.rowcount > 0


# ---- V2 Friend Requests API methods ----

    async def get_incoming_requests_v2(self, user_id: int) -> list[FriendRequest]:
        """Get all incoming friend requests for a user."""
        user = await self.get_by_id(user_id)
        if not user:
            raise LookupError("User not found")
        
        stmt = select(FriendRequest).where(FriendRequest.receiver_id == user_id)
        return self.session.scalars(stmt).all()

    async def get_outgoing_requests_v2(self, user_id: int) -> list[FriendRequest]:
        """Get all outgoing friend requests for a user."""
        user = await self.get_by_id(user_id)
        if not user:
            raise LookupError("User not found")
        
        stmt = select(FriendRequest).where(FriendRequest.requester_id == user_id)
        return self.session.scalars(stmt).all()

    async def create_friend_request_v2(self, requester_id: int, receiver_id: int) -> FriendRequest:
        """Create a friend request between two users."""
        if requester_id == receiver_id:
            raise ValueError("Cannot send a friend request to yourself")
        
        requester = await self.get_by_id(requester_id)
        receiver = await self.get_by_id(receiver_id)
        
        if not requester:
            raise LookupError("User not found")
        if not receiver:
            raise LookupError("Receiver not found")
        
        # Check if they're already friends
        if await self.are_friends_by_ids(requester_id, receiver_id):
            raise ValueError("Users are already friends")
        
        # Check if a request already exists (either direction)
        existing = self.session.scalar(
            select(FriendRequest).where(
                or_(
                    and_(
                        FriendRequest.requester_id == requester_id,
                        FriendRequest.receiver_id == receiver_id,
                    ),
                    and_(
                        FriendRequest.requester_id == receiver_id,
                        FriendRequest.receiver_id == requester_id,
                    ),
                )
            )
        )
        if existing:
            raise ValueError("A friend request already exists between these users")
        
        result = self.session.execute(
            insert(FriendRequest)
            .values(requester_id=requester_id, receiver_id=receiver_id)
            .returning(FriendRequest)
        )
        request = result.scalar_one()
        self.session.commit()
        return request

    async def accept_friend_request_v2(self, receiver_id: int, requester_id: int) -> Friendship:
        """Accept a friend request. Only the receiver can accept."""
        if receiver_id == requester_id:
            raise ValueError("Cannot accept a request from yourself")
        
        receiver = await self.get_by_id(receiver_id)
        requester = await self.get_by_id(requester_id)
        
        if not receiver:
            raise LookupError("User not found")
        if not requester:
            raise LookupError("Requester not found")
        
        # Find the pending request (must be requester -> receiver)
        pending = self.session.scalar(
            select(FriendRequest).where(
                and_(
                    FriendRequest.requester_id == requester_id,
                    FriendRequest.receiver_id == receiver_id,
                )
            )
        )
        
        if not pending:
            raise LookupError("No pending friend request found")
        
        # Normalize IDs for friendship storage
        a, b = self._normalize_pair(requester_id, receiver_id)
        
        # Check if already friends (shouldn't happen, but safety check)
        already = self.session.scalar(
            select(Friendship).where(and_(Friendship.user_id == a, Friendship.friend_id == b))
        )
        if already:
            self.session.execute(delete(FriendRequest).where(FriendRequest.id == pending.id))
            self.session.commit()
            raise ValueError("Users are already friends")
        
        # Create friendship
        result = self.session.execute(
            insert(Friendship).values(user_id=a, friend_id=b).returning(Friendship)
        )
        friendship = result.scalar_one()
        
        # Delete the request
        self.session.execute(delete(FriendRequest).where(FriendRequest.id == pending.id))
        self.session.commit()
        
        return friendship

    async def deny_friend_request_v2(self, receiver_id: int, requester_id: int) -> bool:
        """Deny a friend request. Only the receiver can deny."""
        receiver = await self.get_by_id(receiver_id)
        requester = await self.get_by_id(requester_id)
        
        if not receiver:
            raise LookupError("User not found")
        if not requester:
            raise LookupError("Requester not found")
        
        result = self.session.execute(
            delete(FriendRequest).where(
                and_(
                    FriendRequest.requester_id == requester_id,
                    FriendRequest.receiver_id == receiver_id,
                )
            )
        )
        self.session.commit()
        return result.rowcount > 0

    async def delete_friend_request_v2(self, user_id: int, other_id: int) -> bool:
        """
        Delete a friend request between two users.
        Can be called by either the requester (to cancel) or receiver (to reject).
        """
        user = await self.get_by_id(user_id)
        other = await self.get_by_id(other_id)
        
        if not user:
            raise LookupError("User not found")
        if not other:
            raise LookupError("Other user not found")
        
        # Try to delete in either direction
        result = self.session.execute(
            delete(FriendRequest).where(
                or_(
                    and_(
                        FriendRequest.requester_id == user_id,
                        FriendRequest.receiver_id == other_id,
                    ),
                    and_(
                        FriendRequest.requester_id == other_id,
                        FriendRequest.receiver_id == user_id,
                    ),
                )
            )
        )
        self.session.commit()
        return result.rowcount > 0

    
    # ---- Avatar methods ----
    
    async def create_avatar(self, user_id: int, file: UploadFile) -> None:
        # Verify user exists
        user = await self.get_by_id(user_id)
        if not user:
            raise LookupError("User not found")
        
        # Check if avatar already exists
        avatar_path = AVATAR_DIR / f"user_{user_id}.jpg"
        if avatar_path.exists():
            raise ValueError("Avatar already exists. Use PUT to update.")
        
        # Process and save the avatar
        await self._process_and_save_avatar(user_id, file)

    async def upload_avatar(self, user_id: int, file: UploadFile) -> None:
        # Verify user exists
        user = await self.get_by_id(user_id)
        if not user:
            raise LookupError("User not found")
        
        # Read the uploaded file
        contents = await file.read()
        
        if not contents:
            raise ValueError("Empty file uploaded")
        
        try:
            # Open image with PIL
            image = Image.open(io.BytesIO(contents))
            
            # Convert to RGB if necessary (handles RGBA, P, etc.)
            if image.mode not in ('RGB', 'L'):
                image = image.convert('RGB')
            
            # Crop to square (center crop)
            width, height = image.size
            if width != height:
                # Take the smaller dimension as the crop size
                crop_size = min(width, height)
                
                # Calculate center crop coordinates
                left = (width - crop_size) // 2
                top = (height - crop_size) // 2
                right = left + crop_size
                bottom = top + crop_size
                
                image = image.crop((left, top, right, bottom))
            
            # Resize if larger than max size
            if image.size[0] > AVATAR_MAX_SIZE:
                image = image.resize(
                    (AVATAR_MAX_SIZE, AVATAR_MAX_SIZE),
                    Image.LANCZOS
                )
            
            # Save the processed image
            avatar_path = AVATAR_DIR / f"user_{user_id}.jpg"
            image.save(avatar_path, "JPEG", quality=85, optimize=True)
            
        except Exception as e:
            # Handle invalid image files
            if "cannot identify image file" in str(e).lower() or "image file is truncated" in str(e).lower():
                raise ValueError("Invalid image file")
            raise ValueError(f"Error processing image: {str(e)}")
        
    async def _process_and_save_avatar(self, user_id: int, file: UploadFile) -> None:
        # Validate file extension
        if not file.filename:
            raise ValueError("No filename provided")
        
        file_ext = file.filename.lower().split('.')[-1]
        if file_ext not in ['webp', 'png', 'jpg', 'jpeg']:
            raise ValueError("Invalid file format. Only .webp, .png, and .jpg files are accepted.")
        
        # Read the uploaded file
        contents = await file.read()
        
        if not contents:
            raise ValueError("Empty file uploaded")
        
        try:
            # Open image with PIL
            image = Image.open(io.BytesIO(contents))
            
            # Convert to RGB if necessary (handles RGBA, P, etc.)
            if image.mode not in ('RGB', 'L'):
                image = image.convert('RGB')
            
            # Crop to square (center crop)
            width, height = image.size
            if width != height:
                # Take the smaller dimension as the crop size
                crop_size = min(width, height)
                
                # Calculate center crop coordinates
                left = (width - crop_size) // 2
                top = (height - crop_size) // 2
                right = left + crop_size
                bottom = top + crop_size
                
                image = image.crop((left, top, right, bottom))
            
            # Resize to exact size (256x256)
            if image.size[0] != AVATAR_MAX_SIZE:
                image = image.resize(
                    (AVATAR_MAX_SIZE, AVATAR_MAX_SIZE),
                    Image.LANCZOS
                )
            
            # Save the processed image
            avatar_path = AVATAR_DIR / f"user_{user_id}.jpg"
            image.save(avatar_path, "JPEG", quality=85, optimize=True)
            
        except Exception as e:
            # Handle invalid image files
            if "cannot identify image file" in str(e).lower() or "image file is truncated" in str(e).lower():
                raise ValueError("Invalid image file")
            raise ValueError(f"Error processing image: {str(e)}")
        
    async def get_avatar(self, user_id: int) -> tuple[bytes, str]:
        """
        Retrieve a user's avatar image.
        Returns tuple of (image_bytes, content_type).
        """
        # Verify user exists
        user = await self.get_by_id(user_id)
        if not user:
            raise LookupError("User not found")
        
        avatar_path = AVATAR_DIR / f"user_{user_id}.jpg"
        
        if not avatar_path.exists():
            raise FileNotFoundError("Avatar not found")
        
        with open(avatar_path, "rb") as f:
            image_bytes = f.read()
        
        return image_bytes, "image/jpeg"

    async def delete_avatar(self, user_id: int) -> bool:
        """
        Delete a user's avatar image.
        Returns True if avatar was deleted, False if it didn't exist.
        """
        # Verify user exists
        user = await self.get_by_id(user_id)
        if not user:
            raise LookupError("User not found")
        
        avatar_path = AVATAR_DIR / f"user_{user_id}.jpg"
        
        if not avatar_path.exists():
            raise FileNotFoundError("Avatar not found")
        
        avatar_path.unlink()
        return True


def get_user_repository(db: Session = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


# -------------------- Schemas used by the API/tests --------------------

class UserSchema(BaseModel):
    name: str
    id: int | None = None
    tier: int = 1

    @classmethod
    def from_db_model(cls, user: User) -> "UserSchema":
        return cls(name=user.name, id=user.id, tier=getattr(user, "tier", 1))


class UserCreateSchema(BaseModel):
    name: str
    email: EmailStr
    password: str


class FriendRequestCreateSchema(BaseModel):
    requester: str
    receiver: str


class FriendRequestDecisionSchema(BaseModel):
    requester: str
    receiver: str


class FriendRequestSchema(BaseModel):
    id: int
    requester: str
    receiver: str

    @classmethod
    def from_db_model(cls, request: FriendRequest, requester: User, receiver: User) -> "FriendRequestSchema":
        return cls(id=request.id, requester=requester.name, receiver=receiver.name)


class FriendshipSchema(BaseModel):
    user: str
    friend: str

    @classmethod
    def from_users(cls, user: User, friend: User) -> "FriendshipSchema":
        return cls(user=user.name, friend=friend.name)


class FriendSchema(BaseModel):
    """Schema for friend data in v2 API - excludes password."""
    id: int
    name: str
    email: str

    @classmethod
    def from_db_model(cls, user: User) -> "FriendSchema":
        return cls(id=user.id, name=user.name, email=user.email)
    

class FriendRequestSchemaV2(BaseModel):
    """Schema for friend request in v2 API - includes full user objects."""
    id: int
    requester: FriendSchema
    receiver: FriendSchema

    @classmethod
    def from_db_model(cls, request: FriendRequest, requester: User, receiver: User) -> "FriendRequestSchemaV2":
        return cls(
            id=request.id,
            requester=FriendSchema.from_db_model(requester),
            receiver=FriendSchema.from_db_model(receiver)
        )


class FriendRequestCreateSchemaV2(BaseModel):
    """Schema for creating a friend request in v2 API."""
    receiver_id: int


class FriendRequestActionSchemaV2(BaseModel):
    """Schema for accepting/denying a friend request in v2 API."""
    action: str


class FriendshipSchemaV2(BaseModel):
    """Schema for friendship in v2 API - includes full user objects."""
    user: FriendSchema
    friend: FriendSchema

    @classmethod
    def from_users(cls, user: User, friend: User) -> "FriendshipSchemaV2":
        return cls(
            user=FriendSchema.from_db_model(user),
            friend=FriendSchema.from_db_model(friend)
        )