from .user import Base, User, FriendRequest, Friendship
from .professor import Professor
from .review import Review
from .ai_summary import AISummary
from .ai_summary_history import AISummaryHistory

__all__ = [
    "Base",
    "User",
    "FriendRequest",
    "Friendship",
    "Professor",
    "Review",
    "AISummary",
    "AISummaryHistory",
]
