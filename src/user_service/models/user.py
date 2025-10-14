from pydantic import BaseModel, EmailStr
from sqlalchemy import (
    select,
    insert,
    delete,
    String,
    Integer,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
    and_,
    or_,
)
from sqlalchemy.orm import declarative_base, Session, mapped_column, Mapped
from fastapi import Depends
from sqlalchemy.exc import IntegrityError
import hashlib

from src.shared.database import get_db

Base = declarative_base()
class User(Base):
    """
    User model used by SQLAlchemy to interact with the database. When you look up a user in the database, you will get an instance of this class back. This is the database's view of users.
    """
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  
    name: Mapped[str] = mapped_column(String, unique=True)  
    email: Mapped[str] = mapped_column(String)  
    password: Mapped[str] = mapped_column(String)  


class FriendRequest(Base):
    """
    Represents a pending friend request between two users.
    """

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
            "requester_id",
            "receiver_id",
            name="uq_friend_requests_requester_receiver",
        ),
    )


class Friendship(Base):
    """
    Represents a confirmed friendship between two users. The tuple is stored in
    sorted order so each friendship only appears once in the table.
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


class UserRepository:
    """
    Controls manipulation of the users table.
    """

    def __init__(self, session: Session):
        self.session = session

    async def create(self, name: str, email: str, password: str) -> User:
        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        try:
            stmt = insert(User).values(
                name=name,
                email=email,
                password=hashed_password
            ).returning(User)
            result = self.session.execute(stmt)
            self.session.commit()
            return result.scalar_one()
        except IntegrityError:
            self.session.rollback()
            raise
        except Exception:
            self.session.rollback()
            raise

    async def delete(self, name: str) -> bool:
        try:
            stmt = delete(User).where(User.name == name)
            result = self.session.execute(stmt)
            self.session.commit()
            return result.rowcount > 0
        except Exception:
            self.session.rollback()
            raise
            
    async def get_many(self, limit: int = 100, offset: int = 0, search: str | None = None) -> list[User]:
        """Get a limited number of users, optionally filtered by name."""
        stmt = select(User)
        if search:
            stmt = stmt.where(User.name.ilike(f"%{search}%"))
        stmt = stmt.order_by(User.name).limit(limit).offset(offset)
        users = self.session.scalars(stmt).all()
        return users

    async def count(self, search: str | None = None) -> int:
        """Count total users, optionally filtered by name."""
        from sqlalchemy import func
        stmt = select(func.count()).select_from(User)
        if search:
            stmt = stmt.where(User.name.ilike(f"%{search}%"))
        total = self.session.scalar(stmt)
        return total
        
    async def get_all(self) -> list[User]:
        """Get all users"""
        users = self.session.scalars(select(User)).all()
        return users

    async def get_by_name(self, name: str) -> User | None:
        """Get user by name using an indexed lookup (no full scan)."""
        return self.session.scalars(
            select(User).where(User.name == name).limit(1)
        ).first()

    async def get_by_id(self, user_id: int) -> User | None:
        """Get user by primary key."""
        return self.session.get(User, user_id)

    async def create_friend_request(self, requester_name: str, receiver_name: str) -> FriendRequest:
        """Create a new friend request from requester to receiver."""
        if requester_name == receiver_name:
            raise ValueError("Cannot send a friend request to yourself")

        requester = await self.get_by_name(requester_name)
        receiver = await self.get_by_name(receiver_name)
        if not requester or not receiver:
            raise LookupError("Both users must exist")

        if requester.id is None or receiver.id is None:
            raise ValueError("Users must have ids")

        if await self.are_friends_by_ids(requester.id, receiver.id):
            raise ValueError("Users are already friends")

        existing_request = self.session.scalar(
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
        if existing_request:
            raise ValueError("A friend request already exists between these users")

        try:
            stmt = (
                insert(FriendRequest)
                .values(requester_id=requester.id, receiver_id=receiver.id)
                .returning(FriendRequest)
            )
            result = self.session.execute(stmt)
            self.session.commit()
            return result.scalar_one()
        except Exception:
            self.session.rollback()
            raise

    async def accept_friend_request(self, requester_name: str, receiver_name: str) -> Friendship:
        """Accept an existing friend request and create a friendship."""
        if requester_name == receiver_name:
            raise ValueError("Cannot accept a request from yourself")

        requester = await self.get_by_name(requester_name)
        receiver = await self.get_by_name(receiver_name)
        if not requester or not receiver:
            raise LookupError("Both users must exist")

        if requester.id is None or receiver.id is None:
            raise ValueError("Users must have ids")

        request = self.session.scalar(
            select(FriendRequest).where(
                and_(
                    FriendRequest.requester_id == requester.id,
                    FriendRequest.receiver_id == receiver.id,
                )
            )
        )
        if not request:
            raise LookupError("No pending friend request found")

        lower_id, higher_id = self._normalize_pair(requester.id, receiver.id)

        if await self.are_friends_by_ids(lower_id, higher_id):
            # Users are already friends; remove the stale request.
            self.session.execute(
                delete(FriendRequest).where(FriendRequest.id == request.id)
            )
            self.session.commit()
            raise ValueError("Users are already friends")

        try:
            friendship_stmt = (
                insert(Friendship)
                .values(user_id=lower_id, friend_id=higher_id)
                .returning(Friendship)
            )
            friendship_result = self.session.execute(friendship_stmt)
            self.session.execute(
                delete(FriendRequest).where(FriendRequest.id == request.id)
            )
            self.session.commit()
            return friendship_result.scalar_one()
        except Exception:
            self.session.rollback()
            raise

    async def deny_friend_request(self, requester_name: str, receiver_name: str) -> bool:
        """Remove a pending friend request without creating a friendship."""
        requester = await self.get_by_name(requester_name)
        receiver = await self.get_by_name(receiver_name)
        if not requester or not receiver:
            raise LookupError("Both users must exist")
        if requester.id is None or receiver.id is None:
            raise ValueError("Users must have ids")

        try:
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
        except Exception:
            self.session.rollback()
            raise

    async def list_friend_requests(self, name: str) -> list[FriendRequest]:
        """Return all friend requests involving the specified user."""
        user = await self.get_by_name(name)
        if not user or user.id is None:
            return []
        stmt = select(FriendRequest).where(
            or_(
                FriendRequest.requester_id == user.id,
                FriendRequest.receiver_id == user.id,
            )
        )
        return self.session.scalars(stmt).all()

    async def list_all_friend_requests(self) -> list[FriendRequest]:
        """Return all pending friend requests."""
        return self.session.scalars(select(FriendRequest)).all()

    async def list_friendships(self, name: str) -> list[Friendship]:
        """Return all friendships for the specified user."""
        user = await self.get_by_name(name)
        if not user or user.id is None:
            return []
        stmt = select(Friendship).where(
            or_(
                Friendship.user_id == user.id,
                Friendship.friend_id == user.id,
            )
        )
        return self.session.scalars(stmt).all()

    async def are_friends(self, first_name: str, second_name: str) -> bool:
        """Determine whether two users are already friends."""
        first = await self.get_by_name(first_name)
        second = await self.get_by_name(second_name)
        if not first or not second or first.id is None or second.id is None:
            return False
        return await self.are_friends_by_ids(first.id, second.id)

    async def are_friends_by_ids(self, first_id: int, second_id: int) -> bool:
        """Determine whether two user ids already have a friendship record."""
        lower, higher = self._normalize_pair(first_id, second_id)
        stmt = select(Friendship).where(
            and_(Friendship.user_id == lower, Friendship.friend_id == higher)
        )
        return self.session.scalar(stmt) is not None

    @staticmethod
    def _normalize_pair(first: int, second: int) -> tuple[int, int]:
        """Return the pair ordered ascending so it matches storage expectations."""
        return (first, second) if first < second else (second, first)

def get_user_repository(db: Session = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


class UserSchema(BaseModel):
    """
    The application's view of users. This is how the API represents users (as opposed to how the database represents them).
    """
    name: str
    id: int | None = None

    @classmethod
    def from_db_model(cls, user: User) -> "UserSchema":
        """Create a UserSchema from a User"""
        return cls(name=user.name, id=getattr(user, "id", None))


class UserCreateSchema(BaseModel):
    name: str
    email: EmailStr
    password: str


class FriendRequestCreateSchema(BaseModel):
    requester: str
    receiver: str


class FriendRequestSchema(BaseModel):
    id: int
    requester: str
    receiver: str

    @classmethod
    def from_db_model(
        cls,
        request: FriendRequest,
        requester: User,
        receiver: User,
    ) -> "FriendRequestSchema":
        return cls(
            id=request.id,
            requester=requester.name,
            receiver=receiver.name,
        )


class FriendRequestDecisionSchema(BaseModel):
    requester: str
    receiver: str


class FriendshipSchema(BaseModel):
    user: str
    friend: str

    @classmethod
    def from_users(cls, user: User, friend: User) -> "FriendshipSchema":
        return cls(user=user.name, friend=friend.name)
