import asyncio
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.user_service.models.user import (
    Base,
    UserRepository,
    User,
    FriendRequest,
    Friendship,
)


def get_repo():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    session = Session(engine)
    Base.metadata.create_all(engine)
    return session, UserRepository(session)


def test_create_and_delete_user():
    session, repo = get_repo()

    async def runner():
        # Create a user
        user = await repo.create("testuser", "test@example.com", "pass")
        assert user.name == "testuser"
        # Delete the user
        deleted = await repo.delete("testuser")
        assert deleted is True

    asyncio.run(runner())
    session.close()


def test_get_many_and_count():
    session, repo = get_repo()

    async def runner():
        await repo.create("user1", "user1@example.com", "pass1")
        await repo.create("user2", "user2@example.com", "pass2")
        users = await repo.get_many()
        count = await repo.count()
        assert count == len(users) == 2

    asyncio.run(runner())
    session.close()


def test_get_by_name_and_by_id():
    session, repo = get_repo()

    async def runner():
        user = await repo.create("userX", "userx@example.com", "password")
        user_by_name = await repo.get_by_name("userX")
        user_by_id = await repo.get_by_id(user.id)
        assert user_by_name is not None
        assert user_by_id is not None
        assert user_by_name.id == user.id

    asyncio.run(runner())
    session.close()


def test_create_friend_request_self():
    session, repo = get_repo()

    async def runner():
        with pytest.raises(ValueError, match="Cannot send a friend request to yourself"):
            await repo.create_friend_request("userSelf", "userSelf")

    asyncio.run(runner())
    session.close()


def test_create_friend_request_no_users():
    session, repo = get_repo()

    async def runner():
        with pytest.raises(LookupError, match="Both users must exist"):
            await repo.create_friend_request("nonexistent1", "nonexistent2")

    asyncio.run(runner())
    session.close()


def test_friendship_flow():
    session, repo = get_repo()

    async def runner():
        # Create two users
        alice = await repo.create("Alice", "alice@example.com", "pass")
        bob = await repo.create("Bob", "bob@example.com", "pass")
        # Create a friend request
        friend_req = await repo.create_friend_request("Alice", "Bob")
        assert friend_req is not None
        # Accept the friend request
        friendship = await repo.accept_friend_request("Alice", "Bob")
        assert friendship is not None
        # List friendships and check if they are friends
        friends = await repo.list_friendships("Alice")
        assert len(friends) > 0
        ret = await repo.are_friends("Alice", "Bob")
        assert ret is True

    asyncio.run(runner())
    session.close()


def test_deny_friend_request():
    session, repo = get_repo()

    async def runner():
        # Create two users
        await repo.create("Charlie", "charlie@example.com", "pass")
        await repo.create("David", "david@example.com", "pass")
        # Create a friend request
        await repo.create_friend_request("Charlie", "David")
        # Deny the friend request
        result = await repo.deny_friend_request("Charlie", "David")
        assert result is True

    asyncio.run(runner())
    session.close()


def test_are_friends_by_ids_false():
    session, repo = get_repo()

    async def runner():
        user1 = await repo.create("Eve", "eve@example.com", "pass")
        user2 = await repo.create("Frank", "frank@example.com", "pass")
        are = await repo.are_friends_by_ids(user1.id, user2.id)
        assert are is False

    asyncio.run(runner())
    session.close()
