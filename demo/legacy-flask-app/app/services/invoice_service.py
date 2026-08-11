"""In-memory invoice storage + business rules."""
from app.models.invoice import make_invoice
from app.utils.validation import ValidationError

_invoices: dict[int, dict] = {}
_next_id: int = 1


def reset() -> None:
    global _invoices, _next_id
    _invoices = {}
    _next_id = 1


def list_invoices(status: str | None = None) -> list[dict]:
    values = list(_invoices.values())
    if status:
        values = [i for i in values if i["status"] == status]
    return sorted(values, key=lambda i: i["id"])


def create_invoice(customer: str, amount, description: str = "") -> dict:
    global _next_id
    invoice = make_invoice(_next_id, customer, amount, description)
    _invoices[invoice["id"]] = invoice
    _next_id += 1
    return invoice


def get_invoice(invoice_id: int) -> dict | None:
    return _invoices.get(invoice_id)


def update_invoice(invoice_id: int, data: dict) -> dict | None:
    invoice = _invoices.get(invoice_id)
    if invoice is None:
        return None
    if "amount" in data:
        amount = data["amount"]
        if not isinstance(amount, (int, float)) or amount <= 0:
            raise ValidationError("amount must be a positive number")
        invoice["amount"] = float(amount)
    if "customer" in data:
        customer = data["customer"]
        if not isinstance(customer, str) or not customer.strip():
            raise ValidationError("customer must be a non-empty string")
        invoice["customer"] = customer.strip()
    if "description" in data:
        invoice["description"] = str(data["description"])
    return invoice


def delete_invoice(invoice_id: int) -> bool:
    return _invoices.pop(invoice_id, None) is not None


def mark_paid(invoice_id: int) -> dict | None:
    invoice = _invoices.get(invoice_id)
    if invoice is None:
        return None
    if invoice["status"] == "paid":
        raise ValidationError("invoice is already paid")
    invoice["status"] = "paid"
    return invoice
