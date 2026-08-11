from flask import Blueprint, jsonify, request

from app.services import invoice_service
from app.utils.validation import ValidationError, require_fields

invoices_bp = Blueprint("invoices", __name__)


@invoices_bp.route("/invoices", methods=["GET"])
def list_invoices():
    status = request.args.get("status")
    invoices = invoice_service.list_invoices(status=status)
    return jsonify({"invoices": invoices, "count": len(invoices)})


@invoices_bp.route("/invoices", methods=["POST"])
def create_invoice():
    data = request.get_json(silent=True) or {}
    try:
        require_fields(data, ["customer", "amount"])
        invoice = invoice_service.create_invoice(
            customer=data["customer"],
            amount=data["amount"],
            description=data.get("description", ""),
        )
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(invoice), 201


@invoices_bp.route("/invoices/<int:invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    invoice = invoice_service.get_invoice(invoice_id)
    if invoice is None:
        return jsonify({"error": "invoice not found"}), 404
    return jsonify(invoice)


@invoices_bp.route("/invoices/<int:invoice_id>", methods=["PUT"])
def update_invoice(invoice_id):
    data = request.get_json(silent=True) or {}
    try:
        invoice = invoice_service.update_invoice(invoice_id, data)
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    if invoice is None:
        return jsonify({"error": "invoice not found"}), 404
    return jsonify(invoice)


@invoices_bp.route("/invoices/<int:invoice_id>", methods=["DELETE"])
def delete_invoice(invoice_id):
    deleted = invoice_service.delete_invoice(invoice_id)
    if not deleted:
        return jsonify({"error": "invoice not found"}), 404
    return jsonify({"deleted": invoice_id})


@invoices_bp.route("/invoices/<int:invoice_id>/pay", methods=["POST"])
def pay_invoice(invoice_id):
    try:
        invoice = invoice_service.mark_paid(invoice_id)
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    if invoice is None:
        return jsonify({"error": "invoice not found"}), 404
    return jsonify(invoice)
