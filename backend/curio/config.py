"""Configuration, read from the environment.

Nothing secret is ever hard-coded or committed; see .env.example for the shape.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class Config:
    # ── Core ────────────────────────────────────────────────────────────
    SECRET_KEY = os.environ.get("CURIO_SECRET_KEY", "")
    DATABASE = os.environ.get("CURIO_DB", str(BASE_DIR / "curio.db"))
    # Where the built frontend lands. Flask serves it directly so the Pi
    # doesn't need a second web server in front.
    STATIC_DIR = os.environ.get("CURIO_STATIC_DIR", str(BASE_DIR.parent / "frontend" / "dist"))
    PUBLIC_URL = os.environ.get("CURIO_PUBLIC_URL", "http://localhost:5000").rstrip("/")

    # ── Sessions ────────────────────────────────────────────────────────
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("CURIO_COOKIE_SECURE", True)
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 30  # 30 days

    # ── OpenRouter ──────────────────────────────────────────────────────
    OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
    OPENROUTER_BASE = os.environ.get(
        "OPENROUTER_BASE", "https://openrouter.ai/api/v1"
    ).rstrip("/")
    # Sent as HTTP-Referer/X-Title; OpenRouter uses these for attribution.
    OPENROUTER_TIMEOUT = _int("OPENROUTER_TIMEOUT", 90)

    # Fallback chain used until an admin saves one. Free models churn — these
    # are a starting point to be re-picked from the admin page, not gospel.
    DEFAULT_MODEL_CHAIN = [
        m.strip()
        for m in os.environ.get(
            "CURIO_MODEL_CHAIN",
            "meta-llama/llama-3.3-70b-instruct:free,"
            "google/gemma-2-9b-it:free,"
            "mistralai/mistral-7b-instruct:free",
        ).split(",")
        if m.strip()
    ]

    # ── Abuse guards ────────────────────────────────────────────────────
    # Open signup means the generate endpoints are public. These caps protect
    # the shared free-model daily quota.
    DAILY_CAP_USER = _int("CURIO_DAILY_CAP_USER", 300)
    DAILY_CAP_ANON_IP = _int("CURIO_DAILY_CAP_ANON_IP", 40)
    SIGNUP_CAP_IP = _int("CURIO_SIGNUP_CAP_IP", 5)

    # ── Email (Gmail SMTP + app password, per handoff decision #2) ──────
    SMTP_HOST = os.environ.get("CURIO_SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = _int("CURIO_SMTP_PORT", 587)
    SMTP_USER = os.environ.get("CURIO_SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("CURIO_SMTP_PASSWORD", "")
    MAIL_FROM = os.environ.get("CURIO_MAIL_FROM", "") or os.environ.get("CURIO_SMTP_USER", "")
    MAIL_FROM_NAME = os.environ.get("CURIO_MAIL_FROM_NAME", "Curio")
    # Dry-run prints the email to the log instead of sending. Handy on first deploy.
    MAIL_DRY_RUN = _bool("CURIO_MAIL_DRY_RUN", False)

    # The single admin. First account created with this email is promoted.
    ADMIN_EMAIL = os.environ.get("CURIO_ADMIN_EMAIL", "")
