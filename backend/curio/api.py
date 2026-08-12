"""The app's own API: generation, then persistence.

Generation endpoints are intent-based rather than a `{system, user}` passthrough
— see docs/API.md for why. They all funnel into one `llm.generate()`.
"""
from __future__ import annotations

import json
import logging
import re

from flask import Blueprint, Response, jsonify, request, stream_with_context
from flask_login import current_user, login_required

from . import pagecache, prompts
from .db import execute, get_db, query
from .llm import LLMError, generate, generate_stream
from .ratelimit import check_and_count_generation

log = logging.getLogger(__name__)
bp = Blueprint("api", __name__, url_prefix="/api")

VALID_KINDS = {"fact", "question", "topic"}
MAX_PATH_STEPS = 4        # unbounded history slows every deep tap
MAX_SAID_CHARS = 4000     # keep the prompt bounded no matter how deep the page goes
MAX_TEXT_IN = 500         # any single user-supplied string


# ── helpers ─────────────────────────────────────────────────────────────


def _err(code: str, message: str, status: int):
    return jsonify({"error": code, "message": message}), status


def _body() -> dict:
    return request.get_json(silent=True) or {}


def _clean_text(value, limit: int = MAX_TEXT_IN) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def _clean_list(value, limit: int = 20, item_limit: int = MAX_TEXT_IN) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:limit]:
        text = _clean_text(item, item_limit)
        if text:
            out.append(text)
    return out


def _normalise_buttons(raw, limit: int = 5) -> list[dict]:
    """Free models are loose about the button shape. Coerce it into ours."""
    buttons = []
    if not isinstance(raw, list):
        return buttons
    for item in raw[:limit]:
        if isinstance(item, str):
            label, kind = item, "topic"
        elif isinstance(item, dict):
            label = item.get("label") or item.get("text") or item.get("title") or ""
            kind = item.get("type") or item.get("kind") or "topic"
        else:
            continue
        label = _clean_text(label, 160)
        if not label:
            continue
        buttons.append({"label": label, "type": kind if kind in VALID_KINDS else "topic"})
    return buttons


def _normalise_seeds(raw) -> list[dict]:
    # Seeds allow up to 8 per request; the page-button cap of 5 was silently
    # trimming any bigger hand (a count=6 call really did return 5).
    return _normalise_buttons(raw, limit=8) if isinstance(raw, list) else []


def _gate():
    """Shared rate-limit gate for every generation endpoint."""
    allowed, message = check_and_count_generation()
    if not allowed:
        return _err("quota", message, 429)
    return None


def _generate(system: str, user: str, intent: str):
    try:
        return generate(system, user, intent=intent), None
    except LLMError as exc:
        log.error("generation failed for %s: %s", intent, exc)
        return None, _err(
            "generation_failed",
            "That door didn't open. Every model in the chain came back empty.",
            502,
        )


# ── generation ──────────────────────────────────────────────────────────


@bp.post("/seeds")
def seeds():
    if (blocked := _gate()):
        return blocked
    data = _body()
    count = data.get("count", 4)
    count = count if isinstance(count, int) and 1 <= count <= 8 else 4
    # Deliberately roomier than the other endpoints' exclude lists. This one is
    # the only thing stopping a long session being served the same doors twice,
    # and 20 labels stopped covering that once the client started remembering
    # everything it had dealt.
    exclude = _clean_list(data.get("exclude"), limit=40, item_limit=160)

    system, user = prompts.seeds(count, exclude)
    parsed, error = _generate(system, user, "seeds")
    if error:
        return error

    result = _normalise_seeds(parsed.get("seeds"))
    if not result:
        return _err("generation_failed", "No doors came back. Try again.", 502)
    return jsonify({"seeds": result})


@bp.post("/seeds/topical")
@login_required
def topical_seeds():
    """Doors anchored to the user's saved interests, for the home page row.

    The topics come from email_prefs server-side — the client never sends
    them, so the wire carries only generated labels and the interests stay
    where the user put them.
    """
    row = query(
        "SELECT topics_json FROM email_prefs WHERE user_id = ?",
        (current_user.id,),
        one=True,
    )
    try:
        topics = [t for t in json.loads(row["topics_json"]) if isinstance(t, str) and t.strip()] if row else []
    except (ValueError, TypeError):
        topics = []
    if not topics:
        # Before the gate on purpose: nothing is generated for an empty topic
        # list, and quota counts generations, not requests.
        return jsonify({"seeds": []})

    if (blocked := _gate()):
        return blocked
    data = _body()
    count = data.get("count", 6)
    count = count if isinstance(count, int) and 1 <= count <= 8 else 6
    exclude = _clean_list(data.get("exclude"), limit=40, item_limit=160)

    system, user = prompts.topical_seeds(topics, exclude, count)
    parsed, error = _generate(system, user, "topical_seeds")
    if error:
        return error

    result = _normalise_seeds(parsed.get("seeds"))
    if not result:
        return _err("generation_failed", "No doors came back. Try again.", 502)
    return jsonify({"seeds": result})


@bp.post("/page")
def page():
    data = _body()
    surprise = bool(data.get("surprise"))
    label = _clean_text(data.get("label"), 300)
    kind = data.get("kind")
    kind = kind if kind in VALID_KINDS else "topic"

    if not surprise and not label:
        return _err("bad_request", "Nothing to open.", 400)

    # Cache first, gate second — deliberately. The quota exists to protect the
    # shared free-model budget, and a cache hit spends none of it; charging
    # quota for a SQLite read would punish exactly the taps we made cheap.
    # Surprise pages skip the cache both ways: their promise is somewhere new.
    if not surprise:
        cached = pagecache.get_page(label, kind)
        if cached:
            return jsonify(cached)

    if (blocked := _gate()):
        return blocked
    path = _clean_list(data.get("path"), limit=MAX_PATH_STEPS, item_limit=200)[-MAX_PATH_STEPS:]
    exclude = _clean_list(data.get("exclude"), limit=20, item_limit=200)

    system, user = prompts.page(label, kind, path, surprise, exclude)
    parsed, error = _generate(system, user, "page")
    if error:
        return error

    buttons = _normalise_buttons(parsed.get("buttons"))
    title = _clean_text(parsed.get("title"), 300) or label or "Somewhere unexpected"
    blurb = _clean_text(parsed.get("blurb"), 1200)
    if not blurb:
        return _err("generation_failed", "The page came back empty. Try again.", 502)
    if not surprise:
        # Cached pages ignore the path context ("do not repeat recent steps"),
        # so a hit's buttons may point somewhere already visited. Accepted:
        # the page for a label is coherent from any approach, and keying on
        # path would gut the hit rate this exists for.
        pagecache.store_page(label, kind, title, blurb, buttons)
    return jsonify({"title": title, "blurb": blurb, "buttons": buttons})


@bp.post("/more")
def more():
    if (blocked := _gate()):
        return blocked
    data = _body()
    title = _clean_text(data.get("title"), 300)
    said = _clean_text(data.get("said"), MAX_SAID_CHARS)
    if not title:
        return _err("bad_request", "Which page?", 400)

    system, user = prompts.more(title, said)
    parsed, error = _generate(system, user, "more")
    if error:
        return error
    text = _clean_text(parsed.get("more"), 2000)
    if not text:
        return _err("generation_failed", "Nothing deeper came back.", 502)
    return jsonify({"more": text})


@bp.post("/ask")
def ask():
    if (blocked := _gate()):
        return blocked
    data = _body()
    title = _clean_text(data.get("title"), 300)
    said = _clean_text(data.get("said"), MAX_SAID_CHARS)
    question = _clean_text(data.get("question"), 500)
    if not question:
        return _err("bad_request", "Ask something first.", 400)

    system, user = prompts.ask(title, said, question)
    parsed, error = _generate(system, user, "ask")
    if error:
        return error
    answer = _clean_text(parsed.get("answer"), 2000)
    if not answer:
        return _err("generation_failed", "That one didn't come through.", 502)
    return jsonify({"answer": answer})


class BlurbExtractor:
    """Watches JSON stream out of a model and plucks the blurb text live.

    The page prompt fixes the key order — title, blurb, buttons — so once
    `"blurb"` and its opening quote have gone past, everything up to the
    closing unescaped quote is prose the reader can start reading. This is
    strictly cosmetic: the authoritative page is parsed from the complete
    text afterwards, so when a model mangles its JSON too badly to track the
    extractor just stops emitting and the reader waits for the whole page,
    exactly as before streaming existed.

    Handles: chunk boundaries anywhere (including mid-escape), \\" and \\n
    escapes, and models that use curly quotes for the delimiters themselves.
    """

    _QUOTES = '"“”'

    def __init__(self):
        self._buf = ""          # everything seen, used to find the key
        self._in_blurb = False
        self._done = False
        self._pending_escape = False

    def feed(self, chunk: str) -> str:
        """Consume the next raw chunk, return blurb text ready to show."""
        if self._done:
            return ""
        out = []
        for ch in chunk:
            if self._done:
                break
            if not self._in_blurb:
                self._buf += ch
                if not self._blurb_open():
                    continue
                self._in_blurb = True
                continue
            if self._pending_escape:
                self._pending_escape = False
                out.append({"n": "\n", "t": "\t"}.get(ch, ch))
                continue
            if ch == "\\":
                self._pending_escape = True
                continue
            if ch in self._QUOTES:
                self._done = True
                continue
            out.append(ch)
        return "".join(out)

    def _blurb_open(self) -> bool:
        """True the moment the buffer ends at `"blurb" ... : ... "`."""
        return re.search(r'["“”]blurb["“”]\s*:\s*["“”]$', self._buf) is not None


# ── streaming variants of more/ask ──────────────────────────────────────
#
# These two intents are single prose fields, so their tokens can go straight
# to the screen. The JSON endpoints above remain the client's fallback: the
# fallback chain only operates BEFORE the first streamed token (switching
# models after bytes have shipped would splice two answers), so a mid-stream
# death surfaces as an SSE error event and the client re-asks non-streaming.


def _sse_response(system: str, user: str, intent: str) -> Response:
    def events():
        sent_any = False
        held = ""  # buffer until we know the reply doesn't open with a fence
        try:
            for chunk in generate_stream(system, user, intent):
                if not sent_any:
                    held += chunk
                    stripped = held.lstrip()
                    if not stripped:
                        continue
                    if stripped.startswith("`"):
                        # Model opened with a code fence despite the prose
                        # prompt. Hold until its line ends, then drop it.
                        if "\n" not in stripped:
                            continue
                        held = stripped.split("\n", 1)[1]
                        if not held.strip():
                            continue
                    else:
                        held = stripped
                    sent_any = True
                    yield f"data: {json.dumps(held)}\n\n"
                    continue
                yield f"data: {json.dumps(chunk)}\n\n"
            if not sent_any:
                yield f"event: error\ndata: {json.dumps('Nothing came back.')}\n\n"
                return
            yield "event: done\ndata: {}\n\n"
        except LLMError as exc:
            log.error("stream failed for %s: %s", intent, exc)
            yield f"event: error\ndata: {json.dumps('That answer broke off.')}\n\n"

    return Response(
        # stream_with_context: the generator runs while the response is being
        # consumed, after the view returned — without this, current_app and
        # the per-request DB connection are gone by the first chunk.
        stream_with_context(events()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Tells buffering proxies to pass chunks through as they come.
            "X-Accel-Buffering": "no",
        },
    )


@bp.post("/more/stream")
def more_stream():
    if (blocked := _gate()):
        return blocked
    data = _body()
    title = _clean_text(data.get("title"), 300)
    said = _clean_text(data.get("said"), MAX_SAID_CHARS)
    if not title:
        return _err("bad_request", "Which page?", 400)
    system, user = prompts.more_prose(title, said)
    return _sse_response(system, user, "more")


@bp.post("/ask/stream")
def ask_stream():
    if (blocked := _gate()):
        return blocked
    data = _body()
    title = _clean_text(data.get("title"), 300)
    said = _clean_text(data.get("said"), MAX_SAID_CHARS)
    question = _clean_text(data.get("question"), 500)
    if not question:
        return _err("bad_request", "Ask something first.", 400)
    system, user = prompts.ask_prose(title, said, question)
    return _sse_response(system, user, "ask")


@bp.post("/page/stream")
def page_stream():
    """Streaming door-open: blurb words as they're written, full page at done.

    The page stays structured JSON on the wire from the model; the
    BlurbExtractor forwards just the blurb's characters as they stream, and
    the complete text is then parsed with the same tolerant path as
    /api/page. Cache and quota semantics are identical to /api/page — a
    cache hit is a single immediate done event and costs nothing.
    """
    data = _body()
    surprise = bool(data.get("surprise"))
    label = _clean_text(data.get("label"), 300)
    kind = data.get("kind")
    kind = kind if kind in VALID_KINDS else "topic"

    if not surprise and not label:
        return _err("bad_request", "Nothing to open.", 400)

    if not surprise:
        cached = pagecache.get_page(label, kind)
        if cached:
            return Response(
                f"event: done\ndata: {json.dumps(cached)}\n\n",
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

    if (blocked := _gate()):
        return blocked
    path = _clean_list(data.get("path"), limit=MAX_PATH_STEPS, item_limit=200)[-MAX_PATH_STEPS:]
    exclude = _clean_list(data.get("exclude"), limit=20, item_limit=200)
    system, user = prompts.page(label, kind, path, surprise, exclude)

    def events():
        extractor = BlurbExtractor()
        raw_parts = []
        try:
            for chunk in generate_stream(system, user, "page"):
                raw_parts.append(chunk)
                text = extractor.feed(chunk)
                if text:
                    yield f"data: {json.dumps(text)}\n\n"
        except LLMError as exc:
            log.error("page stream failed: %s", exc)
            yield f"event: error\ndata: {json.dumps('That door did not open.')}\n\n"
            return

        # The streamed blurb was cosmetic; this parse is the real page.
        from .llm import parse_json_loose

        try:
            parsed = parse_json_loose("".join(raw_parts))
        except ValueError:
            yield f"event: error\ndata: {json.dumps('The page came back scrambled. Try again.')}\n\n"
            return
        buttons = _normalise_buttons(parsed.get("buttons"))
        title = _clean_text(parsed.get("title"), 300) or label or "Somewhere unexpected"
        blurb = _clean_text(parsed.get("blurb"), 1200)
        if not blurb:
            yield f"event: error\ndata: {json.dumps('The page came back empty. Try again.')}\n\n"
            return
        if not surprise:
            pagecache.store_page(label, kind, title, blurb, buttons)
        yield f"event: done\ndata: {json.dumps({'title': title, 'blurb': blurb, 'buttons': buttons})}\n\n"

    return Response(
        stream_with_context(events()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@bp.post("/recap")
def recap():
    if (blocked := _gate()):
        return blocked
    path = _clean_list(_body().get("path"), limit=40, item_limit=200)
    if not path:
        return _err("bad_request", "No path to close.", 400)

    system, user = prompts.recap(path)
    parsed, error = _generate(system, user, "recap")
    if error:
        return error
    return jsonify({
        "synthesis": _clean_text(parsed.get("synthesis"), 1500),
        "thread": _clean_text(parsed.get("thread"), 300),
    })


# ── persistence ─────────────────────────────────────────────────────────


def _page_json(row) -> dict:
    def _load(raw, fallback):
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return fallback

    return {
        "id": row["id"],
        "wanderId": row["wander_id"],
        "parentId": row["parent_id"],
        "clientNodeId": row["client_node_id"],
        "parentClientNodeId": row["parent_client_node_id"],
        "kind": row["kind"],
        "title": row["title"],
        "blurb": row["blurb"],
        "more": _load(row["more_json"], []),
        "qa": _load(row["qa_json"], []),
        "buttons": _load(row["buttons_json"], []),
        "createdAt": row["created_at"],
    }


def _own_wander(wander_id: int):
    return query(
        "SELECT * FROM wanders WHERE id = ? AND user_id = ?",
        (wander_id, current_user.id),
        one=True,
    )


@bp.post("/wanders")
@login_required
def create_wander():
    wander_id = execute("INSERT INTO wanders (user_id) VALUES (?)", (current_user.id,))
    row = query("SELECT * FROM wanders WHERE id = ?", (wander_id,), one=True)
    return jsonify({"id": wander_id, "startedAt": row["started_at"]}), 201


@bp.get("/wanders")
@login_required
def list_wanders():
    rows = query(
        """
        SELECT w.id, w.started_at, w.closed_at,
               COUNT(p.id) AS page_count,
               MIN(p.id)   AS first_page,
               MAX(p.id)   AS last_page
        FROM wanders w
        LEFT JOIN pages p ON p.wander_id = w.id
        WHERE w.user_id = ?
        GROUP BY w.id
        ORDER BY w.started_at DESC
        LIMIT 50
        """,
        (current_user.id,),
    )
    out = []
    for r in rows:
        titles = {
            t["id"]: t["title"]
            for t in query(
                "SELECT id, title FROM pages WHERE id IN (?, ?)",
                (r["first_page"], r["last_page"]),
            )
        }
        out.append({
            "id": r["id"],
            "startedAt": r["started_at"],
            "closedAt": r["closed_at"],
            "pageCount": r["page_count"],
            "firstTitle": titles.get(r["first_page"]),
            "lastTitle": titles.get(r["last_page"]),
        })
    return jsonify({"wanders": out})


@bp.get("/wanders/<int:wander_id>")
@login_required
def get_wander(wander_id: int):
    w = _own_wander(wander_id)
    if not w:
        return _err("not_found", "No such wander.", 404)
    pages = query("SELECT * FROM pages WHERE wander_id = ? ORDER BY id", (wander_id,))
    recap_data = None
    if w["recap_json"]:
        try:
            recap_data = json.loads(w["recap_json"])
        except ValueError:
            recap_data = None
    return jsonify({
        "id": w["id"],
        "startedAt": w["started_at"],
        "closedAt": w["closed_at"],
        "recap": recap_data,
        "pages": [_page_json(p) for p in pages],
    })


@bp.post("/wanders/<int:wander_id>/pages")
@login_required
def append_page(wander_id: int):
    if not _own_wander(wander_id):
        return _err("not_found", "No such wander.", 404)
    data = _body()

    title = _clean_text(data.get("title"), 300)
    if not title:
        return _err("bad_request", "A page needs a title.", 400)

    client_node_id = data.get("clientNodeId")
    parent_client_node_id = data.get("parentClientNodeId")

    # Resolve the client's parent node into our own row id.
    parent_id = None
    if parent_client_node_id is not None:
        parent = query(
            "SELECT id FROM pages WHERE wander_id = ? AND client_node_id = ?",
            (wander_id, parent_client_node_id),
            one=True,
        )
        parent_id = parent["id"] if parent else None

    kind = data.get("kind")
    page_id = execute(
        """
        INSERT INTO pages
            (wander_id, parent_id, client_node_id, parent_client_node_id,
             kind, title, blurb, buttons_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(wander_id, client_node_id) WHERE client_node_id IS NOT NULL DO UPDATE SET
            title = excluded.title, blurb = excluded.blurb, buttons_json = excluded.buttons_json
        """,
        (
            wander_id,
            parent_id,
            client_node_id,
            parent_client_node_id,
            kind if kind in VALID_KINDS else None,
            title,
            _clean_text(data.get("blurb"), 4000),
            json.dumps(_normalise_buttons(data.get("buttons"))),
        ),
    )
    # On the UPDATE path lastrowid isn't the row we want — look it up.
    if client_node_id is not None:
        row = query(
            "SELECT id FROM pages WHERE wander_id = ? AND client_node_id = ?",
            (wander_id, client_node_id),
            one=True,
        )
        if row:
            page_id = row["id"]
    return jsonify({"id": page_id}), 201


@bp.patch("/pages/<int:page_id>")
@login_required
def patch_page(page_id: int):
    row = query(
        "SELECT p.id FROM pages p JOIN wanders w ON w.id = p.wander_id "
        "WHERE p.id = ? AND w.user_id = ?",
        (page_id, current_user.id),
        one=True,
    )
    if not row:
        return _err("not_found", "No such page.", 404)

    data = _body()
    sets, args = [], []
    if isinstance(data.get("more"), list):
        sets.append("more_json = ?")
        args.append(json.dumps(_clean_list(data["more"], limit=20, item_limit=4000)))
    if isinstance(data.get("qa"), list):
        qa = []
        for item in data["qa"][:20]:
            if isinstance(item, dict):
                q, a = _clean_text(item.get("q"), 500), _clean_text(item.get("a"), 4000)
                if q:
                    qa.append({"q": q, "a": a})
        sets.append("qa_json = ?")
        args.append(json.dumps(qa))

    if not sets:
        return jsonify({"ok": True})
    args.append(page_id)
    execute(f"UPDATE pages SET {', '.join(sets)} WHERE id = ?", tuple(args))
    return jsonify({"ok": True})


@bp.post("/wanders/<int:wander_id>/close")
@login_required
def close_wander(wander_id: int):
    if not _own_wander(wander_id):
        return _err("not_found", "No such wander.", 404)
    recap_data = _body().get("recap")
    execute(
        "UPDATE wanders SET closed_at = datetime('now'), recap_json = ? WHERE id = ?",
        (json.dumps(recap_data) if recap_data else None, wander_id),
    )
    return jsonify({"ok": True})


@bp.get("/saves")
@login_required
def list_saves():
    rows = query(
        "SELECT p.* FROM saved_pages s JOIN pages p ON p.id = s.page_id "
        "WHERE s.user_id = ? ORDER BY s.created_at DESC",
        (current_user.id,),
    )
    return jsonify({"saves": [_page_json(r) for r in rows]})


@bp.post("/saves")
@login_required
def add_save():
    page_id = _body().get("pageId")
    if not isinstance(page_id, int):
        return _err("bad_request", "Which page?", 400)
    owns = query(
        "SELECT p.id FROM pages p JOIN wanders w ON w.id = p.wander_id "
        "WHERE p.id = ? AND w.user_id = ?",
        (page_id, current_user.id),
        one=True,
    )
    if not owns:
        return _err("not_found", "No such page.", 404)
    execute(
        "INSERT OR IGNORE INTO saved_pages (user_id, page_id) VALUES (?, ?)",
        (current_user.id, page_id),
    )
    return jsonify({"ok": True}), 201


@bp.delete("/saves/<int:page_id>")
@login_required
def remove_save(page_id: int):
    execute(
        "DELETE FROM saved_pages WHERE user_id = ? AND page_id = ?",
        (current_user.id, page_id),
    )
    return jsonify({"ok": True})


@bp.get("/resume")
@login_required
def resume():
    """The return hook. An invitation — shown once, quietly, never counted."""
    w = query(
        "SELECT id FROM wanders WHERE user_id = ? AND closed_at IS NULL "
        "ORDER BY started_at DESC LIMIT 1",
        (current_user.id,),
        one=True,
    )
    wander = None
    if w:
        last = query(
            "SELECT title FROM pages WHERE wander_id = ? ORDER BY id DESC LIMIT 1",
            (w["id"],),
            one=True,
        )
        count = query(
            "SELECT COUNT(*) AS n FROM pages WHERE wander_id = ?", (w["id"],), one=True
        )
        if last:
            wander = {"id": w["id"], "lastTitle": last["title"], "pageCount": count["n"]}

    # A door to come back to, if the last closed wander left a thread hanging.
    door = None
    closed = query(
        "SELECT recap_json FROM wanders WHERE user_id = ? AND recap_json IS NOT NULL "
        "ORDER BY closed_at DESC LIMIT 1",
        (current_user.id,),
        one=True,
    )
    if closed:
        try:
            thread = (json.loads(closed["recap_json"]) or {}).get("thread")
            if thread:
                door = {"label": thread, "type": "question"}
        except (ValueError, TypeError, AttributeError):
            pass

    return jsonify({"wander": wander, "door": door})
