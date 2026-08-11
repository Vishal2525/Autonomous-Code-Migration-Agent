"""Shared request-validation helpers."""


class ValidationError(Exception):
    pass


def require_fields(data: dict, fields: list[str]) -> None:
    missing = [f for f in fields if f not in data or data[f] in (None, "")]
    if missing:
        raise ValidationError(f"missing required fields: {', '.join(missing)}")
