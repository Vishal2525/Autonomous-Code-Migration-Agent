"""User model + construction-time validation."""
from app.utils.validation import ValidationError


def make_user(user_id: int, name, email) -> dict:
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("name must be a non-empty string")
    if not isinstance(email, str) or "@" not in email:
        raise ValidationError("email must be a valid email address")
    return {"id": user_id, "name": name.strip(), "email": email.strip().lower()}
