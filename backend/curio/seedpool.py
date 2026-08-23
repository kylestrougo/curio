"""shared/seed-pool.json — the curated starter doors, read server-side.

The same file the frontend imports for its instant first paint. The server
uses it in two places: warm-cache (pre-generating pages overnight) and the
daily email for users with no saved topics (random doors, no LLM call).
"""
from __future__ import annotations

import json
import random


def load_pool() -> list[dict]:
    """Every well-formed entry in the pool, or [] if it can't be read."""
    # config.BASE_DIR is resolved at call time (attribute access, not a
    # from-import): tests monkeypatch it to point the pool somewhere else.
    from . import config

    path = config.BASE_DIR.parent / "shared" / "seed-pool.json"
    try:
        pool = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(pool, list):
        return []
    return [s for s in pool if isinstance(s, dict) and s.get("label")]


def sample_doors(count: int = 4, rng=None) -> list[dict]:
    """Random doors from the pool, preferring one per domain."""
    rng = rng or random
    pool = load_pool()
    rng.shuffle(pool)
    picked, seen = [], set()
    for s in pool:  # first pass: spread across domains
        if s.get("domain") in seen:
            continue
        picked.append(s)
        seen.add(s.get("domain"))
        if len(picked) == count:
            break
    for s in pool:  # top up if there were fewer domains than doors
        if len(picked) == count:
            break
        if s not in picked:
            picked.append(s)
    return [{"label": s["label"], "type": s.get("type", "topic")} for s in picked]
