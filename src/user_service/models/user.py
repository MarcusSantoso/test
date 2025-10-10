from pydantic import BaseModel, EmailStr
from sqlalchemy import select, insert, delete, String, Integer
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

    async def get_all(self) -> list[User]:
        """Get all users"""
        users = self.session.scalars(select(User)).all()
        return users

    async def get_by_name(self, name: str) -> User | None:
        """Get user by name using an indexed lookup (no full scan)."""
        return self.session.scalars(
            select(User).where(User.name == name).limit(1)
        ).first()

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