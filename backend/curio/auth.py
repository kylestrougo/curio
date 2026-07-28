"""Accounts. Deliberately light — this is a self-hosted personal app.

Handoff decision #1: open self-signup, email + password, argon2 hashes,
Flask-Login session cookies, with per-IP rate limiting on signup.
"""
from __future__ import annotations

import re
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from flask import Blueprint, current_app, jsonify, request
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user

from .db import execute, query
from .ratelimit import check_signup_rate

bp = Blueprint("auth", __name__, url_prefix="/api/auth")
login_manager = LoginManager()

# Low-memory argon2 parameters — this is a Pi 3 with 1GB shared between
# several services. Still far above the bar for a personal app.
_hasher = PasswordHasher(time_cost=2, memory_cost=32 * 1024, parallelism=1)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 10


class User(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.email = row["email"]
        self.role = row["role"]

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def as_json(self) -> dict:
        return {"id": self.id, "email": self.email, "role": self.role}


@login_manager.user_loader
def load_user(user_id: str):
    row = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    return User(row) if row else None


@login_manager.unauthorized_handler
def _unauthorized():
    # An API, not a redirect-to-login site.
    return jsonify({"error": "unauthorized", "message": "Sign in to do that."}), 401


def init_app(app) -> None:
    login_manager.init_app(app)
    app.register_blueprint(bp)


def _ensure_email_prefs(user_id: int) -> None:
    """Every user gets a prefs row, disabled. Configure nothing, get nothing."""
    execute(
        "INSERT OR IGNORE INTO email_prefs (user_id, enabled, unsub_token) VALUES (?, 0, ?)",
        (user_id, secrets.token_urlsafe(24)),
    )


@bp.post("/signup")
def signup():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not EMAIL_RE.match(email):
        return jsonify({"error": "bad_email", "message": "That doesn't look like an email address."}), 400
    if len(password) < MIN_PASSWORD:
        return jsonify({
            "error": "weak_password",
            "message": f"Use at least {MIN_PASSWORD} characters.",
        }), 400

    allowed, msg = check_signup_rate()
    if not allowed:
        return jsonify({"error": "rate_limited", "message": msg}), 429

    if query("SELECT id FROM users WHERE email = ?", (email,), one=True):
        return jsonify({"error": "email_taken", "message": "That email already has an account."}), 409

    # The configured admin email gets the single admin role on first signup.
    admin_email = (current_app.config.get("ADMIN_EMAIL") or "").strip().lower()
    already_admin = query("SELECT id FROM users WHERE role = 'admin'", (), one=True)
    role = "admin" if (admin_email and email == admin_email and not already_admin) else "user"

    user_id = execute(
        "INSERT INTO users (email, password_hash, role) VALUES (?, ?, ?)",
        (email, _hasher.hash(password), role),
    )
    _ensure_email_prefs(user_id)

    row = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    user = User(row)
    login_user(user, remember=True)
    return jsonify({"user": user.as_json()}), 201


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    row = query("SELECT * FROM users WHERE email = ?", (email,), one=True)
    # Same response whether the email is unknown or the password is wrong.
    bad = jsonify({"error": "bad_credentials", "message": "Email or password didn't match."}), 401
    if not row:
        return bad
    try:
        _hasher.verify(row["password_hash"], password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return bad

    if _hasher.check_needs_rehash(row["password_hash"]):
        execute("UPDATE users SET password_hash = ? WHERE id = ?", (_hasher.hash(password), row["id"]))

    _ensure_email_prefs(row["id"])
    user = User(row)
    login_user(user, remember=True)
    return jsonify({"user": user.as_json()})


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    return jsonify({"ok": True})


@bp.get("/me")
def me():
    """Never 401s — the client uses this to decide which UI to show."""
    if current_user.is_authenticated:
        return jsonify({"user": current_user.as_json()})
    return jsonify({"user": None})
