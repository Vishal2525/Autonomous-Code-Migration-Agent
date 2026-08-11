"""Invoice model + construction-time validation."""
from app.utils.validation import ValidationError


def make_invoice(invoice_id: int, customer, amount, description: str = "") -> dict:
    if not isinstance(customer, str) or not customer.strip():
        raise ValidationError("customer must be a non-empty string")
    if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount <= 0:
        raise ValidationError("amount must be a positive number")
    return {
        "id": invoice_id,
        "customer": customer.strip(),
        "amount": float(amount),
        "description": str(description),
        "status": "draft",
    }
