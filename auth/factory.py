from flask import Flask
from werkzeug.exceptions import HTTPException
from sqlalchemy.exc import IntegrityError
from config import get_config
from extensions import db, migrate, jwt
from security import ApiError

def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(get_config())
    if test_config:
        app.config.update(test_config)
    smtp_required = [
        "SMTP_HOST",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "MAIL_FROM"
    ]
    for key in smtp_required:
        if not app.config.get(key):
            raise RuntimeError(
                f"Missing SMTP configuration: {key}"
            )

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    import models
    from routes import auth_bp
    app.register_blueprint(auth_bp)
    @app.errorhandler(ApiError)
    def handle_api_error(error):
        db.session.rollback()
        return{"error":error.message}, error.status
    @app.errorhandler(IntegrityError)
    def handle_integrity_error(error):
        db.session.rollback()
        return{"error": "Database constraint violation"}, 409

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        return{"error": error.description}, error.code
    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        db.session.rollback()
        app.logger.exception("Unexpected error")
        return{"error": "Internal server error"}, 500
    @app.get("/health")
    def health():
        return {"service":"auth", "status":"ok"},200

    @app.get("/")
    def index():
        return{
            "service": "Auth service",
            "version": "1.0.0",
            "status":"running"
        }, 200
    return app


