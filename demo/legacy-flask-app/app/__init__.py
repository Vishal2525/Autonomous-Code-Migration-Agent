from flask import Flask

from app.routes.health import health_bp
from app.routes.invoices import invoices_bp
from app.routes.users import users_bp
from app.services import invoice_service, user_service


def create_app() -> Flask:
    app = Flask(__name__)
    invoice_service.reset()
    user_service.reset()
    app.register_blueprint(health_bp)
    app.register_blueprint(invoices_bp, url_prefix="/api")
    app.register_blueprint(users_bp, url_prefix="/api")
    return app
