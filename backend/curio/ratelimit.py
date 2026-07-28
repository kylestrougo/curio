"""Abuse guards for a publicly-reachable app with open signup.

The thing actually being protected is the *shared free-model daily quota*: one
heavy user, or one script that found the URL, can starve everyone else. Counters
live in SQLite rather than memory so they survive a restart and are visible to
the cron job.

This is intentionally coarse — a daily bucket, not a token bucket. It is a
quota guard, not a DDoS defence; Cloudflare sits in front for that.
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import current_app, request
from flask_login import current_user

from .db import execute, get_db, query


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def client_ip() -> str:
    """Real client IP behind the Cloudflare Tunnel.

    CF-Connecting-IP is set by Cloudflare and, because the Pi is only reachable
    *through* the tunnel, cannot be spoofed by an outside caller. X-Forwarded-For
    is honoured second for a plain local reverse proxy.
    """
    cf = request.headers.get("CF-Connecting-IP")
    if cf:
        return cf.strip()
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _subject() -> tuple[str, int]:
    """Who is being counted, and what their daily cap is."""
    cfg = current_app.config
    if current_user.is_authenticated:
        return f"user:{current_user.id}", cfg["DAILY_CAP_USER"]
    return f"ip:{client_ip()}", cfg["DAILY_CAP_ANON_IP"]


def check_and_count_generation() -> tuple[bool, str]:
    """Atomically increment today's counter and report whether it's allowed."""
    subject, cap = _subject()
    day = _today()
    db = get_db()
    # UPSERT returning the new value — one statement, no read-then-write race.
    cur = db.execute(
        "INSERT INTO usage_counters (subject, day, count) VALUES (?, ?, 1) "
        "ON CONFLICT(subject, day) DO UPDATE SET count = count + 1 "
        "RETURNING count",
        (subject, day),
    )
    used = cur.fetchone()[0]
    cur.close()
    db.commit()

    if used > cap:
        if subject.startswith("ip:"):
            return False, (
                "You've hit today's limit for signed-out wandering. "
                "Making an account raises it — and keeps your trail."
            )
        return False, "You've reached today's generation limit. It resets at midnight UTC."
    return True, ""


def check_signup_rate() -> tuple[bool, str]:
    """Cap accounts created per IP per day."""
    cap = current_app.config["SIGNUP_CAP_IP"]
    subject, day = f"signup:{client_ip()}", _today()
    db = get_db()
    cur = db.execute(
        "INSERT INTO usage_counters (subject, day, count) VALUES (?, ?, 1) "
        "ON CONFLICT(subject, day) DO UPDATE SET count = count + 1 "
        "RETURNING count",
        (subject, day),
    )
    used = cur.fetchone()[0]
    cur.close()
    db.commit()
    if used > cap:
        return False, "Too many accounts created from here today."
    return True, ""


def prune_counters(keep_days: int = 7) -> int:
    """Housekeeping for the nightly cron — the table is otherwise unbounded."""
    db = get_db()
    cur = db.execute(
        "DELETE FROM usage_counters WHERE day < date('now', ?)", (f"-{int(keep_days)} days",)
    )
    n = cur.rowcount
    cur.close()
    db.commit()
    return n
