"""The daily email — "doors for today".

Product constraint, from the brief, that governs every line here: this is an
**invitation, not a hook**. Concretely that means:

* Users who configure nothing get nothing. `enabled` defaults to 0.
* No open tracking pixels, no click tracking, no "we miss you" copy, no
  streaks, no escalating frequency.
* One-click unsubscribe, no login required, honoured instantly.

Delivery is Gmail SMTP with an app password (handoff decision #2), reusing the
pattern already working on this Pi.
"""
from __future__ import annotations

import html
import json
import logging
import secrets
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr

from flask import Blueprint, current_app, jsonify, redirect, request
from flask_login import current_user, login_required

from . import prompts
from .db import execute, query
from .llm import LLMError, generate

log = logging.getLogger(__name__)
bp = Blueprint("email", __name__)

FREQUENCIES = {"daily", "weekdays", "weekly"}


# ── preferences ─────────────────────────────────────────────────────────


def _prefs_row(user_id: int):
    row = query("SELECT * FROM email_prefs WHERE user_id = ?", (user_id,), one=True)
    if not row:
        execute(
            "INSERT INTO email_prefs (user_id, enabled, unsub_token) VALUES (?, 0, ?)",
            (user_id, secrets.token_urlsafe(24)),
        )
        row = query("SELECT * FROM email_prefs WHERE user_id = ?", (user_id,), one=True)
    return row


def _prefs_json(row) -> dict:
    try:
        topics = json.loads(row["topics_json"])
    except (ValueError, TypeError):
        topics = []
    return {
        "enabled": bool(row["enabled"]),
        "topics": topics,
        "wildcard": bool(row["wildcard"]),
        "sendHour": row["send_hour"],
        "frequency": row["frequency"],
        "lastSentOn": row["last_sent_on"],
    }


@bp.get("/api/email-prefs")
@login_required
def get_prefs():
    return jsonify(_prefs_json(_prefs_row(current_user.id)))


@bp.put("/api/email-prefs")
@login_required
def put_prefs():
    _prefs_row(current_user.id)  # ensure it exists
    data = request.get_json(silent=True) or {}

    topics = []
    if isinstance(data.get("topics"), list):
        for t in data["topics"][:15]:
            if isinstance(t, str) and t.strip():
                topics.append(t.strip()[:80])

    hour = data.get("sendHour", 8)
    hour = hour if isinstance(hour, int) and 0 <= hour <= 23 else 8

    frequency = data.get("frequency", "daily")
    frequency = frequency if frequency in FREQUENCIES else "daily"

    execute(
        "UPDATE email_prefs SET enabled = ?, topics_json = ?, wildcard = ?, "
        "send_hour = ?, frequency = ? WHERE user_id = ?",
        (
            1 if data.get("enabled") else 0,
            json.dumps(topics),
            1 if data.get("wildcard", True) else 0,
            hour,
            frequency,
            current_user.id,
        ),
    )
    return jsonify(_prefs_json(_prefs_row(current_user.id)))


# ── unsubscribe + deep links ────────────────────────────────────────────


@bp.get("/unsub/<token>")
def unsubscribe(token: str):
    """One click, no login, instant. Never a 'are you sure?' interstitial."""
    row = query("SELECT user_id FROM email_prefs WHERE unsub_token = ?", (token,), one=True)
    if row:
        execute("UPDATE email_prefs SET enabled = 0 WHERE user_id = ?", (row["user_id"],))
    # Same page either way — an invalid token shouldn't confirm or deny an account.
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<title>Unsubscribed — Curio</title>"
        "<style>body{font-family:Georgia,serif;background:#F4F2EB;color:#1C2B3A;"
        "display:grid;place-items:center;height:100vh;margin:0;text-align:center;padding:24px}"
        "a{color:#A9781F}</style>"
        "<div><h1>Unsubscribed.</h1>"
        "<p>No more daily doors. You can turn them back on any time in settings.</p>"
        f"<p><a href='{html.escape(current_app.config['PUBLIC_URL'])}'>Back to Curio</a></p></div>"
    )


@bp.get("/api/door/<token>")
def resolve_door(token: str):
    """Exchange an emailed deep-link token for the door it points at."""
    row = query("SELECT label, kind FROM door_tokens WHERE token = ?", (token,), one=True)
    if not row:
        return jsonify({"error": "not_found", "message": "That door has closed."}), 404
    return jsonify({"label": row["label"], "type": row["kind"]})


@bp.get("/d/<token>")
def deep_link(token: str):
    """Email link → the app, already opening that door."""
    return redirect(f"{current_app.config['PUBLIC_URL']}/?door={token}", code=302)


# ── sending ─────────────────────────────────────────────────────────────


def _make_door_token(user_id: int, label: str, kind: str) -> str:
    token = secrets.token_urlsafe(12)
    execute(
        "INSERT INTO door_tokens (token, user_id, label, kind) VALUES (?, ?, ?, ?)",
        (token, user_id, label, kind),
    )
    return token


def _render(email: str, doors: list[dict], unsub_token: str) -> tuple[str, str]:
    base = current_app.config["PUBLIC_URL"]
    unsub_url = f"{base}/unsub/{unsub_token}"

    lines = ["Doors for today", "", ]
    for d in doors:
        lines.append(f"  {d['label']}")
        lines.append(f"  {base}/d/{d['token']}")
        lines.append("")
    lines += ["—", "Turn these off any time: " + unsub_url]
    text = "\n".join(lines)

    items = "".join(
        f"<li style='margin:0 0 18px'>"
        f"<a href='{base}/d/{html.escape(d['token'])}' "
        f"style='color:#1C2B3A;font-size:19px;text-decoration:none;"
        f"border-bottom:2px solid #A9781F;padding-bottom:2px'>"
        f"{html.escape(d['label'])}</a></li>"
        for d in doors
    )
    html_body = (
        "<div style='background:#F4F2EB;padding:32px 20px;font-family:Georgia,serif;color:#1C2B3A'>"
        "<div style='max-width:520px;margin:0 auto'>"
        "<p style='font-family:Helvetica,Arial,sans-serif;font-size:11px;letter-spacing:2px;"
        "text-transform:uppercase;color:#A9781F;font-weight:600;margin:0 0 18px'>Curio — doors for today</p>"
        f"<ul style='list-style:none;padding:0;margin:0 0 28px;line-height:1.4'>{items}</ul>"
        "<p style='font-size:14px;color:#4A5A68;line-height:1.6;margin:0 0 24px'>"
        "Follow one, or none. They'll keep just as well tomorrow.</p>"
        "<p style='font-family:Helvetica,Arial,sans-serif;font-size:11px;color:#4A5A68'>"
        f"<a href='{html.escape(unsub_url)}' style='color:#4A5A68'>Stop these emails</a></p>"
        "</div></div>"
    )
    return text, html_body


def _send(to_email: str, subject: str, text: str, html_body: str) -> bool:
    cfg = current_app.config
    if cfg["MAIL_DRY_RUN"]:
        log.info("[DRY RUN] would email %s: %s\n%s", to_email, subject, text)
        return True
    if not cfg["SMTP_USER"] or not cfg["SMTP_PASSWORD"]:
        log.error("SMTP not configured; skipping email to %s", to_email)
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg["MAIL_FROM_NAME"], cfg["MAIL_FROM"]))
    msg["To"] = to_email
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")

    try:
        _deliver(cfg["SMTP_HOST"], int(cfg["SMTP_PORT"]), cfg["SMTP_USER"], cfg["SMTP_PASSWORD"], msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        log.error("failed to send to %s: %s", to_email, exc)
        return False


def _deliver(host: str, port: int, user: str, password: str, msg) -> None:
    """Send over whichever transport the port implies.

    Gmail offers both, and they are not interchangeable: 465 expects TLS from
    the first byte, while 587 opens in clear text and upgrades via STARTTLS.
    Calling starttls() on 465 hangs until the timeout; connecting plain to 587
    and skipping the upgrade would send the app password in the clear. Choosing
    off the port means a config that works elsewhere works here unchanged.
    """
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
        return
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(msg)


def _is_due(prefs, now: datetime) -> bool:
    """Frequency + hour gate, plus a send-once-per-day guard."""
    today = now.strftime("%Y-%m-%d")
    if prefs["last_sent_on"] == today:
        return False
    if now.hour < prefs["send_hour"]:
        return False

    freq = prefs["frequency"]
    weekday = now.weekday()  # Mon=0
    if freq == "weekdays" and weekday > 4:
        return False
    if freq == "weekly" and weekday != 0:
        return False
    return True


def _last_thread(user_id: int) -> str | None:
    """The 'thread to carry' from the user's last closed wander — nice continuity."""
    row = query(
        "SELECT recap_json FROM wanders WHERE user_id = ? AND recap_json IS NOT NULL "
        "ORDER BY closed_at DESC LIMIT 1",
        (user_id,),
        one=True,
    )
    if not row:
        return None
    try:
        return (json.loads(row["recap_json"]) or {}).get("thread") or None
    except (ValueError, TypeError, AttributeError):
        return None


def send_due_emails(force_user_id: int | None = None) -> dict:
    """Called by cron via `flask send-due-emails`. One generation call per user."""
    now = datetime.now(timezone.utc)
    rows = query(
        "SELECT p.*, u.email FROM email_prefs p JOIN users u ON u.id = p.user_id "
        "WHERE p.enabled = 1" + (" AND p.user_id = ?" if force_user_id else ""),
        (force_user_id,) if force_user_id else (),
    )

    sent = skipped = failed = 0
    for prefs in rows:
        if force_user_id is None and not _is_due(prefs, now):
            skipped += 1
            continue

        try:
            topics = json.loads(prefs["topics_json"])
        except (ValueError, TypeError):
            topics = []

        system, user = prompts.email_doors(
            topics, bool(prefs["wildcard"]), _last_thread(prefs["user_id"])
        )
        try:
            parsed = generate(system, user, intent="email")
        except LLMError as exc:
            log.error("door generation failed for user %s: %s", prefs["user_id"], exc)
            failed += 1
            continue

        doors = []
        for seed in (parsed.get("seeds") or [])[:4]:
            if not isinstance(seed, dict):
                continue
            label = (seed.get("label") or "").strip()[:160]
            if not label:
                continue
            kind = seed.get("type")
            kind = kind if kind in {"fact", "question", "topic"} else "topic"
            doors.append(
                {"label": label, "kind": kind, "token": _make_door_token(prefs["user_id"], label, kind)}
            )
        if not doors:
            failed += 1
            continue

        text, html_body = _render(prefs["email"], doors, prefs["unsub_token"])
        if _send(prefs["email"], "Doors for today", text, html_body):
            execute(
                "UPDATE email_prefs SET last_sent_on = ? WHERE user_id = ?",
                (now.strftime("%Y-%m-%d"), prefs["user_id"]),
            )
            sent += 1
        else:
            failed += 1

    return {"sent": sent, "skipped": skipped, "failed": failed}
