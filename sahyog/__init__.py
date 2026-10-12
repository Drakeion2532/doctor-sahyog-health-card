"""Doctor Sahyog – QR-code based digital health card."""
from __future__ import annotations

import os
from pathlib import Path

from flask import Flask
from flask_login import LoginManager
from flask_wtf import CSRFProtect

from .models import db, User

csrf = CSRFProtect()
login_manager = LoginManager()
login_manager.login_view = "auth.login"


def _dev_key(instance: str) -> str:
    """For local runs only: persist a random Fernet key in instance/. In
    production set SAHYOG_FIELD_KEY from a secrets manager."""
    from .security import generate_key
    path = Path(instance) / "field.key"
    Path(instance).mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(generate_key())
    return path.read_text().strip()


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.config.update(
        SECRET_KEY=os.environ.get("SAHYOG_SECRET_KEY", "dev-only-change-me"),
        FIELD_ENCRYPTION_KEY=os.environ.get("SAHYOG_FIELD_KEY") or _dev_key(app.instance_path),
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "SAHYOG_DB", "sqlite:///" + str(Path(app.instance_path) / "sahyog.db")),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PUBLIC_BASE_URL=os.environ.get("SAHYOG_PUBLIC_URL", "http://127.0.0.1:5000"),
        MAX_LOGIN_FAILURES=5,
    )
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)

    from .routes import auth, patient, doctor, card, admin
    for bp in (auth.bp, patient.bp, doctor.bp, card.bp, admin.bp):
        app.register_blueprint(bp)

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self'"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    with app.app_context():
        db.create_all()
    return app


@login_manager.user_loader
def load_user(uid):
    return db.session.get(User, int(uid))
