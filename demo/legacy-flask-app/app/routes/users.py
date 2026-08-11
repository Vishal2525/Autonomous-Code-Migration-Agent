from flask import Blueprint, jsonify, request

from app.services import user_service
from app.utils.validation import ValidationError, require_fields

users_bp = Blueprint("users", __name__)


@users_bp.route("/users", methods=["GET"])
def list_users():
    users = user_service.list_users()
    return jsonify({"users": users, "count": len(users)})


@users_bp.route("/users", methods=["POST"])
def create_user():
    data = request.get_json(silent=True) or {}
    try:
        require_fields(data, ["name", "email"])
        user = user_service.create_user(name=data["name"], email=data["email"])
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(user), 201


@users_bp.route("/users/<int:user_id>", methods=["GET"])
def get_user(user_id):
    user = user_service.get_user(user_id)
    if user is None:
        return jsonify({"error": "user not found"}), 404
    return jsonify(user)
