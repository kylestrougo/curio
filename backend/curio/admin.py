"""Admin surface: which free model is actually behaving this week.

Free models churn constantly, so the point of this page is fast vetting —
see the catalogue, see our own success stats, reorder the chain, and test a
model's JSON discipline before trusting it. Changes take effect immediately;
no restart.
"""
from __future__ import annotations

from functools import wraps

import requests
from flask import Blueprint, jsonify, request
from flask_login import current_user

from . import prompts
from .llm import (
    CONFIG_KEY_CHAIN,
    CONFIG_KEY_OVERRIDES,
    generate_raw,
    get_chain,
    get_overrides,
    list_free_models,
    set_config_json,
    stats_rollup,
)

bp = Blueprint("admin", __name__, url_prefix="/api/admin")

# Intents the admin test button can exercise, mapped to a representative prompt.
TEST_INTENTS = {
    "page": lambda: prompts.page("Why do we dream?", "question", [], False, []),
    "seeds": lambda: prompts.seeds(4, []),
    "more": lambda: prompts.more("Why do we dream?", "Dreams occur mostly in REM sleep."),
    "ask": lambda: prompts.ask(
        "Why do we dream?", "Dreams occur mostly in REM sleep.", "Do animals dream too?"
    ),
    "recap": lambda: prompts.recap(["Sleep", "REM", "Lucid dreaming"]),
}


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"error": "unauthorized", "message": "Sign in to do that."}), 401
        if getattr(current_user, "role", "user") != "admin":
            return jsonify({"error": "forbidden", "message": "Admins only."}), 403
        return fn(*args, **kwargs)

    return wrapper


@bp.get("/models")
@admin_required
def models():
    """The OpenRouter free catalogue, joined with our own recent stats."""
    try:
        catalogue = list_free_models()
    except requests.RequestException as exc:
        return jsonify({
            "error": "openrouter_unreachable",
            "message": f"Couldn't reach OpenRouter: {exc}",
        }), 502

    stats = {s["model"]: s for s in stats_rollup(days=7)["models"]}
    for m in catalogue:
        m["stats"] = stats.get(m["id"])
    return jsonify({"models": catalogue, "chain": get_chain()})


@bp.get("/config")
@admin_required
def get_config():
    return jsonify({"chain": get_chain(), "overrides": get_overrides()})


@bp.put("/config")
@admin_required
def put_config():
    data = request.get_json(silent=True) or {}

    if "chain" in data:
        chain = data["chain"]
        if not isinstance(chain, list) or not chain:
            return jsonify({
                "error": "bad_request",
                "message": "The chain needs at least one model.",
            }), 400
        cleaned = []
        for m in chain[:8]:
            if isinstance(m, str) and m.strip() and m.strip() not in cleaned:
                cleaned.append(m.strip())
        if not cleaned:
            return jsonify({"error": "bad_request", "message": "No valid model ids."}), 400
        set_config_json(CONFIG_KEY_CHAIN, cleaned)

    if "overrides" in data:
        overrides = data["overrides"]
        if not isinstance(overrides, dict):
            return jsonify({"error": "bad_request", "message": "Overrides must be an object."}), 400
        cleaned_ov = {
            k: v.strip()
            for k, v in overrides.items()
            if k in TEST_INTENTS and isinstance(v, str) and v.strip()
        }
        set_config_json(CONFIG_KEY_OVERRIDES, cleaned_ov)

    return jsonify({"chain": get_chain(), "overrides": get_overrides()})


@bp.post("/test")
@admin_required
def test():
    """Run one real generation and show raw + parsed — the fastest way to vet a model."""
    data = request.get_json(silent=True) or {}
    model = (data.get("model") or "").strip()
    intent = data.get("intent") or "page"
    if not model:
        return jsonify({"error": "bad_request", "message": "Pick a model to test."}), 400
    if intent not in TEST_INTENTS:
        return jsonify({
            "error": "bad_request",
            "message": f"Unknown intent. One of: {', '.join(TEST_INTENTS)}",
        }), 400

    system, user = TEST_INTENTS[intent]()
    result = generate_raw(model, system, user)
    result["model"] = model
    result["intent"] = intent
    return jsonify(result)


@bp.get("/stats")
@admin_required
def stats():
    days = request.args.get("days", type=int) or 7
    return jsonify(stats_rollup(days=max(1, min(days, 90))))
