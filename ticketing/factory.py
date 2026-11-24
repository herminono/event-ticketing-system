from flask import Flask
from werkzeug.exceptions import HTTPException
from sqlalchemy.exc import IntegrityError
from config import get_config
from extensions import db, migrate, jwt,limiter
from helpers import ApiError

def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(get_config())
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError("Missing DATABASE_URL")
    if not app.config.get("JWT_PUBLIC_KEY"):
        raise RuntimeError("Missing JWT_PUBLIC_KEY")
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    limiter.init_app(app)

    import models
    from event_routes import event_bp
    from ticket_routes import ticket_bp
    from order_routes import order_bp

    app.register_blueprint(event_bp)
    app.register_blueprint(ticket_bp)
    app.register_blueprint(order_bp)
    @app.errorhandler(ApiError)
    def handle_api_error(error):
        db.session.rollback()
        return {"error":error.message}, error.status

    @app.errorhandler(IntegrityError)
    def handle_integrity_error(error):
        db.session.rollback()
        return {"error": "Database constraint violation"}, 409

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        return {"error": error.description}, error.code
    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        db.session.rollback()
        app.logger.exception("Unexpected server error")
        return {"error": "Internal server error"}, 500
    @app.errorhandler(429)
    def handle_rate_limit(error):
        return {"error": "Too many requests"}, 429
    @app.get("/health")
    def health():
        return {"service":"ticketing","status":"ok"}, 200

    @app.get("/")
    def index():
        return {
            "service": "Ticketing Service",
            "version": "1.0.0",
            "status": "running"
        }, 200
    return app
