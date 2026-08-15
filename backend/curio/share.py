"""Share a page: freeze what's on screen behind an opaque token.

A share is a snapshot, not a live reference — the recipient sees exactly what
the sharer saw, served straight from the database with no LLM call and no
quota spent. Wandering onward from the shared page uses the normal (public)
generation endpoints.
"""
from __future__ import annotations

import html
import json
import secrets

from flask import Blueprint, current_app, jsonify, redirect, request
from flask_login import current_user, login_required

from .api import VALID_KINDS, _clean_text, _normalise_buttons, _normalise_terms
from .db import execute, query

bp = Blueprint("share", __name__)


@bp.post("/api/share")
@login_required
def create_share():
    """Freeze the page the sharer is looking at. Pure DB — no generation."""
    data = request.get_json(silent=True) or {}
    title = _clean_text(data.get("title"), 300)
    if not title:
        return jsonify({"error": "bad_request", "message": "Nothing to share."}), 400
    blurb = _clean_text(data.get("blurb"), 4000)
    kind = data.get("kind")
    kind = kind if kind in VALID_KINDS else None
    # Same caps as PATCH /api/pages — the [[term]] markers inside more/qa
    # pass through untouched so the recipient's links still work.
    more = []
    for item in (data.get("more") or [])[:20]:
        text = _clean_text(item, 4000)
        if text:
            more.append(text)
    qa = []
    for item in (data.get("qa") or [])[:20]:
        if not isinstance(item, dict):
            continue
        q = _clean_text(item.get("q"), 500)
        a = _clean_text(item.get("a"), 4000)
        if q:
            qa.append({"q": q, "a": a})
    buttons = _normalise_buttons(data.get("buttons"))
    terms = _normalise_terms(data.get("terms"), blurb, title)
    token = secrets.token_urlsafe(12)
    execute(
        "INSERT INTO shared_pages"
        " (token, user_id, kind, title, blurb, more_json, qa_json, buttons_json, terms_json)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            token,
            current_user.id,
            kind,
            title,
            blurb,
            json.dumps(more),
            json.dumps(qa),
            json.dumps(buttons),
            json.dumps(terms),
        ),
    )
    return jsonify({"token": token, "url": f"{current_app.config['PUBLIC_URL']}/s/{token}"}), 201


def _loads_list(raw):
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return value if isinstance(value, list) else []


@bp.get("/api/share/<token>")
def get_share(token: str):
    """The snapshot, verbatim. Public — no login, no quota."""
    row = query("SELECT * FROM shared_pages WHERE token = ?", (token,), one=True)
    if not row:
        return jsonify({"error": "not_found", "message": "That page has wandered off."}), 404
    return jsonify(
        {
            "title": row["title"],
            "blurb": row["blurb"],
            "kind": row["kind"],
            "more": _loads_list(row["more_json"]),
            "qa": _loads_list(row["qa_json"]),
            "buttons": _loads_list(row["buttons_json"]),
            "terms": _loads_list(row["terms_json"]),
        }
    )


@bp.get("/s/<token>")
def share_landing(token: str):
    """The link people actually receive.

    An HTML page rather than a 302: iMessage's preview crawler doesn't run
    JavaScript or follow meta-refreshes, so the og: tags here are what makes
    a texted link show the page's title and first lines. Humans are bounced
    on to the app immediately by the refresh.
    """
    row = query("SELECT title, blurb FROM shared_pages WHERE token = ?", (token,), one=True)
    if not row:
        return redirect("/", code=302)  # stale link → home, quietly
    title = html.escape(row["title"])
    desc = html.escape(row["blurb"][:200])
    tok = html.escape(token)
    canonical = html.escape(f"{current_app.config['PUBLIC_URL']}/s/{token}")
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{title} — Curio</title>"
        f"<meta property=\"og:title\" content=\"{title}\">"
        f"<meta property=\"og:description\" content=\"{desc}\">"
        "<meta property=\"og:site_name\" content=\"Curio\">"
        "<meta property=\"og:type\" content=\"article\">"
        f"<meta property=\"og:url\" content=\"{canonical}\">"
        f"<meta http-equiv=\"refresh\" content=\"0;url=/?share={tok}\">"
        "</head><body style=\"font-family:Georgia,serif;background:#F4F2EB;"
        "color:#1C2B3A;padding:40px\">"
        f"<p><a href=\"/?share={tok}\">{title} — open in Curio</a></p>"
        "</body></html>"
    )
