"""In-memory user storage."""
from app.models.user import make_user

_users: dict[int, dict] = {}
_next_id: int = 1


def reset() -> None:
    global _users, _next_id
    _users = {}
    _next_id = 1


def list_users() -> list[dict]:
    return sorted(_users.values(), key=lambda u: u["id"])


def create_user(name: str, email: str) -> dict:
    global _next_id
    user = make_user(_next_id, name, email)
    _users[user["id"]] = user
    _next_id += 1
    return user


def get_user(user_id: int) -> dict | None:
    return _users.get(user_id)
