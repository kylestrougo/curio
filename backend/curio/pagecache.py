"""The page cache: tap something anyone has tapped before, skip the LLM.

This is the sanctioned answer to slow doors. The project's law — one LLM call
per tap, never speculative client prefetch — is about not multiplying calls;
a cache *removes* them. Three decisions worth knowing:

* **Keyed on (label, kind), not the path.** The page prompt includes the last
  few trail steps, so a cached page loses that nuance — a button might point
  somewhere the user just was. Accepted: the content of "Why do rivers
  meander?" is coherent from any direction, and keying on path would destroy
  the hit rate that is the entire point.

* **Surprise pages are never cached.** Their whole promise is somewhere new.

* **Writes are one row, reads are one row, and the hit counter is
  best-effort** — a failed bookkeeping UPDATE must never take down a page
  that was otherwise free to serve.

Entries expire by age via housekeeping (prune), not on read: an evergreen
page a week stale is fine, and the nightly cron already exists.
"""
from __future__ import annotations

import json
import logging

from .db import execute, query

log = logging.getLogger(__name__)

TTL_DAYS = 7


def cache_key(label: str, kind: str) -> str:
    return f"{label.strip().lower()}:{kind}"


def get_page(label: str, kind: str) -> dict | None:
    """The cached page for this tap, or None. Counts the hit, best-effort."""
    row = query(
        "SELECT label, kind, title, blurb, buttons_json, terms_json "
        "FROM page_cache WHERE cache_key = ?",
        (cache_key(label, kind),),
        one=True,
    )
    if not row:
        return None
    try:
        buttons = json.loads(row["buttons_json"])
    except (ValueError, TypeError):
        return None  # a corrupt row is a miss, not an error
    # Rows cached before the terms column simply have none to link — the
    # page is still perfectly good, so never turn that into a miss.
    try:
        terms = json.loads(row["terms_json"] or "[]")
        if not isinstance(terms, list):
            terms = []
    except (ValueError, TypeError):
        terms = []
    try:
        execute(
            "UPDATE page_cache SET hits = hits + 1 WHERE cache_key = ?",
            (cache_key(label, kind),),
        )
    except Exception:  # pragma: no cover - bookkeeping only
        log.warning("cache hit-count update failed for %r", label)
    return {"title": row["title"], "blurb": row["blurb"], "buttons": buttons, "terms": terms}


def store_page(
    label: str,
    kind: str,
    title: str,
    blurb: str,
    buttons: list,
    terms: list | None = None,
    model: str | None = None,
) -> None:
    execute(
        "INSERT INTO page_cache (cache_key, label, kind, title, blurb, buttons_json, terms_json, model) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(cache_key) DO UPDATE SET "
        "title = excluded.title, blurb = excluded.blurb, "
        "buttons_json = excluded.buttons_json, terms_json = excluded.terms_json, "
        "model = excluded.model, created_at = datetime('now')",
        (
            cache_key(label, kind),
            label.strip(),
            kind,
            title,
            blurb,
            json.dumps(buttons),
            json.dumps(terms or []),
            model,
        ),
    )


def has_page(label: str, kind: str) -> bool:
    """Existence check without touching the hit counter (warm-cache uses it)."""
    return (
        query(
            "SELECT 1 FROM page_cache WHERE cache_key = ?",
            (cache_key(label, kind),),
            one=True,
        )
        is not None
    )


def prune(days: int = TTL_DAYS) -> int:
    """Drop entries older than `days`. Returns how many went."""
    before = query("SELECT COUNT(*) AS n FROM page_cache", (), one=True)["n"]
    execute(
        "DELETE FROM page_cache WHERE created_at < datetime('now', ?)",
        (f"-{int(days)} days",),
    )
    after = query("SELECT COUNT(*) AS n FROM page_cache", (), one=True)["n"]
    return before - after
