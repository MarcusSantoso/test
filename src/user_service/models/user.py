from pydantic import BaseModel 
from sqlalchemy import select, insert, delete, String
from sqlalchemy.orm import declarative_base, Session, mapped_column, Mapped
from fastapi import Depends

from shared.database import get_db

Base = declarative_base()
class User(Base):
    """
    User model used by SQLAlchemy to interact with the database. When you look up a user in the database, you will get an instance of this class back. This is the database's view of users.
    """
    __tablename__ = "users"
    name: Mapped[str] = mapped_column(String, primary_key=True)

class UserRepository:
    """
    Controls manipulation of the users table.
    """

    def __init__(self, session: Session):
        self.session = session

    async def create(self, name: str) -> User:
        result = self.session.execute(insert(User), [{"name": name}])
        self.session.commit()
        return User(name=name)

    async def delete(self, name: str) -> None:
        user = await self.get_by_name(name)
        stmt = delete(User).where(User.name == name)
        result = self.session.execute(stmt)
        self.session.commit()
        return result

    async def get_all(self) -> list[User]:
        """Get all users"""
        users = self.session.scalars(select(User)).all()
        return users

    async def get_by_name(self, name: str) -> User:
        """Get user by name"""
        user = next((u for u in await self.get_all() if u.name == name), None)
        return user

def get_user_repository(db: Session = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


class UserSchema(BaseModel):
    """
    The application's view of users. This is how the API represents users (as opposed to how the database represents them).
    """
    name: str

    @classmethod
    def from_db_model(cls, user: User) -> "UserSchema":
        """Create a UserSchema from a User"""
        return cls(name=user.name)

