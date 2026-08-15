"""CLI commands. Cron calls these — no long-lived scheduler process.

Keeping the scheduler out of the Flask process is deliberate: an APScheduler
thread would sit in memory all day on a Pi 3 that's already running several
services. `cron` costs nothing when it isn't running.
"""
from __future__ import annotations

import click
from flask.cli import with_appcontext

from . import pagecache, prompts
from .db import execute, query
from .email_ import send_due_emails
from .llm import get_chain, stats_rollup
from .ratelimit import prune_counters


@click.command("send-due-emails")
@click.option("--user-id", type=int, default=None, help="Force-send to one user, ignoring schedule.")
@with_appcontext
def send_due_emails_command(user_id):
    """Generate and send the daily doors to everyone who's due."""
    result = send_due_emails(force_user_id=user_id)
    click.echo(f"sent={result['sent']} skipped={result['skipped']} failed={result['failed']}")


@click.command("housekeeping")
@with_appcontext
def housekeeping_command():
    """Nightly tidy: prune old rate-limit counters, stats, and spent door tokens."""
    counters = prune_counters(keep_days=7)
    execute("DELETE FROM model_stats WHERE created_at < datetime('now', '-30 days')")
    execute("DELETE FROM door_tokens WHERE created_at < datetime('now', '-30 days')")
    pages = pagecache.prune()
    click.echo(
        f"pruned {counters} rate-limit counters and {pages} cached pages; "
        "stats and door tokens older than 30d removed"
    )


@click.command("make-admin")
@click.argument("email")
@with_appcontext
def make_admin_command(email):
    """Promote an existing account to admin."""
    row = query("SELECT id FROM users WHERE email = ?", (email.strip().lower(),), one=True)
    if not row:
        raise click.ClickException(f"No account for {email}")
    execute("UPDATE users SET role = 'admin' WHERE id = ?", (row["id"],))
    click.echo(f"{email} is now an admin.")


@click.command("model-status")
@click.option("--days", type=int, default=7)
@with_appcontext
def model_status_command(days):
    """Which free models are behaving, from the terminal."""
    click.echo(f"chain: {' → '.join(get_chain())}\n")
    rollup = stats_rollup(days=days)
    if not rollup["models"]:
        click.echo(f"No calls in the last {days} days.")
        return
    for m in rollup["models"]:
        p50 = f"{m['p50Ms']}ms" if m["p50Ms"] is not None else "—"
        click.echo(f"{m['okRate']:>6.1%}  {m['calls']:>5} calls  p50 {p50:>8}  {m['model']}")
        if m["lastError"]:
            click.echo(f"         last error: {m['lastError'][:100]}")


def _check_page_contract(parsed) -> str | None:
    """Return a human reason the page is unusable, or None if it honours the shape.

    Latency alone is a trap: a model that answers in two seconds with four
    buttons, or with a type the UI has no colour for, is worse than a slower
    one that gets it right. Speed only counts among models that pass this.
    """
    if not isinstance(parsed, dict):
        return "not an object"
    if not isinstance(parsed.get("title"), str) or not parsed["title"].strip():
        return "no title"
    if not isinstance(parsed.get("blurb"), str) or not parsed["blurb"].strip():
        return "no blurb"
    buttons = parsed.get("buttons")
    if not isinstance(buttons, list):
        return "no buttons"
    if len(buttons) != 5:
        return f"{len(buttons)} buttons, want 5"
    for b in buttons:
        if not isinstance(b, dict):
            return "button not an object"
        if not isinstance(b.get("label"), str) or not b["label"].strip():
            return "button without a label"
        if b.get("type") not in ("fact", "question", "topic"):
            return f"bad button type: {b.get('type')!r}"
    words = len(parsed["blurb"].split())
    if words > 60:
        return f"blurb {words} words, want under ~45"
    return None


def _bench(ids, repeat, echo=None):
    """Time each model on a real page generation. Returns [(ms|None, id, failure)].

    Sequential on purpose: firing these in parallel measures the free tier's
    rate limiter rather than the models.
    """
    from statistics import median

    from . import prompts
    from .llm import generate_raw

    system, user = prompts.page("Why do we dream?", "question", [], False, [])
    results = []
    for mid in ids:
        latencies, failure = [], None
        for _ in range(repeat):
            r = generate_raw(mid, system, user, intent="bench")
            if not r["ok"]:
                failure = (r["error"] or "failed")[:60]
                break
            reason = _check_page_contract(r["parsed"])
            if reason:
                failure = f"off-contract: {reason}"
                break
            latencies.append(r["latencyMs"])
        if failure:
            results.append((None, mid, failure))
            if echo:
                echo(f"  ✗ {mid} — {failure}")
        else:
            ms = int(median(latencies))
            results.append((ms, mid, None))
            if echo:
                echo(f"  ✓ {mid} — {ms}ms")
    return results


def _usable(results):
    return sorted([r for r in results if r[0] is not None])


@click.command("bench-models")
@click.option("--models", default=None, help="Comma-separated model ids. Defaults to the current chain.")
@click.option("--all-free", is_flag=True, help="Benchmark every free model in the catalogue (slow).")
@click.option("--repeat", type=int, default=1, help="Calls per model; median is reported.")
@with_appcontext
def bench_models_command(models, all_free, repeat):
    """Time the free models on a real page generation and check the JSON contract."""
    from .llm import list_free_models

    if models:
        ids = [m.strip() for m in models.split(",") if m.strip()]
    elif all_free:
        ids = [m["id"] for m in list_free_models()]
    else:
        ids = get_chain()
    if not ids:
        click.echo("Nothing to benchmark.")
        return

    est = len(ids) * repeat * 12
    click.echo(f"{len(ids)} model(s) × {repeat} — roughly {est // 60}m{est % 60:02d}s if all respond\n")

    good = _usable(_bench(ids, repeat, echo=click.echo))
    click.echo("\n── usable, fastest first ──")
    if not good:
        click.echo("None passed. Try --all-free, or check the key and quota.")
        return
    for ms, mid, _ in good:
        click.echo(f"{ms:>7}ms  {mid}")
    click.echo("\nSuggested chain (paste into /admin, or CURIO_MODEL_CHAIN):")
    click.echo(",".join(mid for _, mid, _ in good[:3]))


@click.command("refresh-chain")
@click.option("--force", is_flag=True, help="Re-rank even when the current chain still works.")
@click.option("--repeat", type=int, default=3, help="Calls per model; median is used.")
@click.option("--top", type=int, default=3, help="How many models to keep in the chain.")
@click.option("--dry-run", is_flag=True, help="Report what would change, change nothing.")
@with_appcontext
def refresh_chain_command(force, repeat, top, dry_run):
    """Repair the model chain when it has rotted. Intended for cron.

    The free catalogue churns: models are renamed and retired without notice,
    and a chain that worked last week can be entirely dead this week. This
    checks the chain still functions and rebuilds it from the catalogue when it
    doesn't.

    By default it will NOT reorder a chain that is merely slower than some
    alternative. Speed is the only thing that can be measured automatically,
    and it is a poor proxy for whether pages are worth reading — the contract
    check catches malformed JSON, not dull or inaccurate writing. Promoting on
    latency alone would let the product's voice drift with no one deciding it
    should. Use --force when you have decided you want the fastest survivors,
    or re-pick deliberately from /admin.
    """
    from .llm import CONFIG_KEY_CHAIN, list_free_models, set_config_json

    current = get_chain()
    click.echo(f"chain: {' → '.join(current) or '(empty)'}")

    working = _usable(_bench(current, repeat, echo=click.echo)) if current else []
    if working and not force:
        click.echo(f"chain is healthy ({len(working)}/{len(current)} usable) — leaving it alone")
        return

    click.echo("chain is dead — rebuilding from the catalogue" if not force else "forced re-rank")
    catalogue = [m["id"] for m in list_free_models()]
    if not catalogue:
        click.echo("catalogue returned nothing — leaving the chain alone")
        raise SystemExit(1)

    ranked = _usable(_bench(catalogue, repeat, echo=click.echo))
    if not ranked:
        # Better a stale chain than none: an empty chain makes every tap fail.
        click.echo("nothing in the catalogue passed — leaving the chain alone")
        raise SystemExit(1)

    new = [mid for _, mid, _ in ranked[:top]]
    if new == current:
        click.echo("no change")
        return
    if dry_run:
        click.echo(f"would set: {' → '.join(new)}")
        return
    set_config_json(CONFIG_KEY_CHAIN, new)
    click.echo(f"chain updated: {' → '.join(new)}")


@click.command("warm-cache")
@click.option("--limit", type=int, default=12, help="Most doors to generate in one run.")
@with_appcontext
def warm_cache_command(limit):
    """Pre-generate pages for starter doors that aren't cached yet.

    The starter pool in shared/seed-pool.json is what every visitor sees
    first; generating those pages overnight means their first tap opens
    instantly instead of waiting multi-seconds on a free model.

    Sequential on purpose — parallel calls measure the free tier's rate
    limiter, which is the reverted-prefetch stampede all over again. Runs off
    cron, so it bypasses the per-user quota (that guards user-triggered
    generation); the only budget spent is the shared OpenRouter key's, which
    is why the nightly limit stays small.
    """
    import json as _json
    import random as _random

    from .config import BASE_DIR
    from .llm import LLMError, generate

    pool_path = BASE_DIR.parent / "shared" / "seed-pool.json"
    try:
        pool = _json.loads(pool_path.read_text())
    except (OSError, ValueError) as exc:
        raise click.ClickException(f"can't read {pool_path}: {exc}")

    todo = [
        s for s in pool
        if isinstance(s, dict) and s.get("label")
        and not pagecache.has_page(s["label"], s.get("type", "topic"))
    ]
    _random.shuffle(todo)  # spread coverage rather than always warming the top

    warmed = failures = 0
    for seed in todo[:limit]:
        label, kind = seed["label"], seed.get("type", "topic")
        system, user = prompts.page(label, kind, [], False, [])
        try:
            parsed = generate(system, user, intent="page")
        except LLMError as exc:
            failures += 1
            click.echo(f"  ✗ {label} — {str(exc)[:80]}")
            # Three straight failures means the chain is probably down;
            # walking a dead chain for every remaining door helps nobody.
            if failures >= 3 and warmed == 0:
                click.echo("aborting: chain looks dead (try refresh-chain)")
                raise SystemExit(1)
            continue

        title = (parsed.get("title") or label).strip()[:300]
        blurb = (parsed.get("blurb") or "").strip()[:1200]
        buttons = [
            {"label": str(b.get("label", "")).strip()[:160],
             "type": b.get("type") if b.get("type") in ("fact", "question", "topic") else "topic"}
            for b in (parsed.get("buttons") or []) if isinstance(b, dict) and b.get("label")
        ][:5]
        if not blurb or not buttons:
            failures += 1
            click.echo(f"  ✗ {label} — page came back empty")
            continue
        terms = [
            str(t).strip()[:80]
            for t in (parsed.get("terms") or [])
            if isinstance(t, str) and t.strip() and t.strip().lower() in blurb.lower()
        ][:4]
        pagecache.store_page(label, kind, title, blurb, buttons, terms)
        warmed += 1
        click.echo(f"  ✓ {label}")

    click.echo(f"warmed={warmed} failed={failures} already_cached={len(pool) - len(todo)}")


# ── door-speed diagnostics ──────────────────────────────────────────────
#
# "Doors feel slow" has two very different causes with identical symptoms:
# the free model itself degraded (happens constantly, no fault of ours), or a
# code change made the same model slower. model_stats records every call, so
# the database already contains the answer — diagnose-doors reads it, and
# bench-experiments then isolates each candidate knob with live A/B calls.


def _pctl(sorted_ms: list, frac: float):
    if not sorted_ms:
        return None
    return sorted_ms[min(len(sorted_ms) - 1, int(len(sorted_ms) * frac))]


def _period_stats(rows) -> dict:
    """model → {calls, ok, p50, p95} for one before/after period."""
    out: dict[str, dict] = {}
    for r in rows:
        s = out.setdefault(r["model"], {"calls": 0, "ok": 0, "lat": []})
        s["calls"] += 1
        if r["ok"]:
            s["ok"] += 1
            if r["latency_ms"] is not None:
                s["lat"].append(r["latency_ms"])
    for s in out.values():
        lat = sorted(s.pop("lat"))
        s["p50"], s["p95"] = _pctl(lat, 0.5), _pctl(lat, 0.95)
    return out


@click.command("diagnose-doors")
@click.option("--since", default=None,
              help="Boundary timestamp (e.g. '2026-08-10 14:00'); default 36 hours ago.")
@with_appcontext
def diagnose_doors_command(since):
    """Read the evidence on door (page) speed — no model calls, instant.

    Splits recorded page-generation latency at the deploy boundary, checks
    how often the first chain model is failing (each failure silently adds a
    long wait before the backup answers), and whether the page cache is
    actually serving anything.
    """
    from .llm import chain_for, get_overrides

    boundary = since or query(
        "SELECT datetime('now', '-36 hours') AS t", (), one=True
    )["t"]
    chain = chain_for("page")
    overrides = get_overrides()

    click.echo(f"chain for page: {' → '.join(chain)}")
    if overrides.get("page"):
        click.echo(f"page override: {overrides['page']}")
    click.echo(f"boundary: {boundary} (before = pre-deploy, after = post-deploy)\n")

    rows = query(
        "SELECT model, ok, latency_ms, created_at FROM model_stats "
        "WHERE intent = 'page' ORDER BY created_at",
        (),
    )
    before = _period_stats([r for r in rows if r["created_at"] < boundary])
    after = _period_stats([r for r in rows if r["created_at"] >= boundary])

    click.echo("page generation by model (ok-rate, p50/p95 ms):")
    for model in sorted(set(before) | set(after)):
        for label, side in (("before", before.get(model)), ("after ", after.get(model))):
            if side:
                ok_rate = side["ok"] / side["calls"]
                click.echo(
                    f"  {label} {ok_rate:>5.0%}  {side['calls']:>4} calls"
                    f"  p50 {side['p50'] or '—'}  p95 {side['p95'] or '—'}  {model}"
                )
    if not rows:
        click.echo("  (no page calls recorded at all)")

    click.echo("\nverdicts:")
    verdicts = 0

    # Same model, both periods, meaningfully slower after → a real regression.
    for model in set(before) & set(after):
        b, a = before[model], after[model]
        if b["p50"] and a["p50"] and b["calls"] >= 3 and a["calls"] >= 3:
            if a["p50"] > b["p50"] * 1.3:
                click.echo(
                    f"  ⚠ REGRESSION: {model} p50 rose {b['p50']}ms → {a['p50']}ms "
                    "across the boundary — same model, slower answers. "
                    "Run bench-experiments to isolate which setting is responsible."
                )
                verdicts += 1
            elif a["p50"] < b["p50"] * 1.15:
                click.echo(
                    f"  ✓ {model}: no regression ({b['p50']}ms → {a['p50']}ms) — "
                    "this model did not get slower."
                )
                verdicts += 1

    # First-chain-model failures: the silent latency everyone actually feels.
    first = chain[0] if chain else None
    fa = after.get(first)
    if fa and fa["calls"] >= 3:
        fail_rate = 1 - fa["ok"] / fa["calls"]
        if fail_rate > 0.2:
            click.echo(
                f"  ⚠ FALLTHROUGH: {first} failed {fail_rate:.0%} of page calls since the "
                "boundary. Every failure adds its full wait before the next model "
                "answers — this is the classic 'doors got slow'. Fix: "
                "`flask bench-models --all-free` then repoint the chain from /admin."
            )
            verdicts += 1
    models_after = {m for m, s in after.items() if s["ok"]}
    if first and after and first not in models_after:
        click.echo(
            f"  ⚠ {first} has answered nothing since the boundary — "
            "pages are being served entirely by backup models."
        )
        verdicts += 1

    # Cache reality.
    c = query(
        "SELECT COUNT(*) AS n, COALESCE(SUM(hits),0) AS hits, MAX(created_at) AS newest "
        "FROM page_cache", (), one=True,
    )
    if c["n"] == 0:
        click.echo(
            "  ⚠ page cache is EMPTY — repeat doors are regenerating every time. "
            "Run `flask warm-cache --limit 12` and install its cron line."
        )
    else:
        click.echo(
            f"  ✓ cache: {c['n']} pages, {c['hits']} hits served free (newest entry {c['newest']})."
        )
    if not verdicts and rows:
        click.echo(
            "  no clear per-model verdict (few calls on shared models across the "
            "boundary) — bench-experiments will give a live answer."
        )


# The pre-v2 prompt, verbatim, so bench-experiments can isolate what the v2
# prompt additions cost. A benchmark artifact — production lives in prompts.py.
_OLD_PERSONA = (
    "You are Curio, the knowledge engine behind a curiosity app. The user explores by tapping. "
    "You are accurate and never invent facts. You write for a curious, intelligent adult and prize "
    "the genuinely fascinating over the obvious."
)


def _experiment_arms(repeat: int) -> list[dict]:
    from .llm import INTENT_TEMPERATURE

    system, user = prompts.page("Why do we dream?", "question", [], False, [])
    old_system = (
        _OLD_PERSONA + " For the item the user just tapped," + prompts._PAGE_SHAPE
        + " Do not repeat recent steps in the path."
    )
    slim_system = "You write fascinating, accurate micro-articles. " + prompts._PAGE_SHAPE
    temp = INTENT_TEMPERATURE["page"]

    base = {"system": system, "user": user, "json_mode": True, "temperature": temp, "max_tokens": 1000}
    return [
        {"key": "baseline", "why": "production settings today", **base},
        {"key": "no-temp", "why": "pre-v2 sampling (no temperature field)", **{**base, "temperature": None}},
        {"key": "no-json-mode", "why": "drop response_format", **{**base, "json_mode": False}},
        {"key": "old-persona", "why": "pre-v2 prompt", **{**base, "system": old_system}},
        {"key": "slim-prompt", "why": "minimal prompt", **{**base, "system": slim_system}},
        {"key": "max-600", "why": "shorter reply budget", **{**base, "max_tokens": 600}},
    ]


@click.command("bench-experiments")
@click.option("--model", "model_id", default=None, help="Model to test (default: first in the page chain).")
@click.option("--repeat", type=int, default=3, help="Rounds per arm.")
@with_appcontext
def bench_experiments_command(model_id, repeat):
    """A/B the door-speed knobs on the live model — one change per arm.

    Rounds are interleaved (arm 1..6, then again) so free-tier drift over the
    run can't flatter whichever arm happened to go last, and calls are
    sequential for the same reason _bench is. Replies are contract-checked so
    a fast-but-broken arm can't win. Nothing is recorded to model_stats —
    experiments must not pollute the admin page.
    """
    import time as _time

    from .llm import LLMError, chain_for, parse_json_loose, _post
    import requests as _requests

    model_id = model_id or (chain_for("page") or [None])[0]
    if not model_id:
        raise click.ClickException("no model configured")

    arms = _experiment_arms(repeat)
    results = {a["key"]: {"ok": 0, "calls": 0, "lat": [], "chars": [], "last_fail": None} for a in arms}

    click.echo(f"model: {model_id}   rounds: {repeat}   calls: {repeat * len(arms)}\n")
    for rnd in range(repeat):
        for arm in arms:
            r = results[arm["key"]]
            r["calls"] += 1
            started = _time.monotonic()
            try:
                raw = _post(
                    model_id, arm["system"], arm["user"], arm["max_tokens"],
                    json_mode=arm["json_mode"], temperature=arm["temperature"],
                )
            except (LLMError, _requests.RequestException) as exc:
                r["last_fail"] = str(exc)[:80]
                click.echo(f"  ✗ {arm['key']:<14} {r['last_fail']}")
                continue
            ms = int((_time.monotonic() - started) * 1000)
            try:
                parsed = parse_json_loose(raw)
                reason = _check_page_contract(parsed)
            except ValueError:
                reason = "unparseable"
            if reason:
                r["last_fail"] = reason
                click.echo(f"  ✗ {arm['key']:<14} {ms}ms but off-contract: {reason}")
                continue
            r["ok"] += 1
            r["lat"].append(ms)
            r["chars"].append(len(raw))
            click.echo(f"  ✓ {arm['key']:<14} {ms}ms")
        if rnd == 0 and all(not results[a["key"]]["ok"] for a in arms):
            click.echo("\nevery arm failed round 1 — the model looks down, not slow. "
                       "Run `flask bench-models --all-free` instead.")
            raise SystemExit(1)

    click.echo(f"\n{'arm':<14} {'ok':>5} {'p50':>7} {'p95':>7} {'chars':>6}  why")
    baseline_p50 = None
    for arm in arms:
        r = results[arm["key"]]
        lat = sorted(r["lat"])
        p50, p95 = _pctl(lat, 0.5), _pctl(lat, 0.95)
        if arm["key"] == "baseline":
            baseline_p50 = p50
        chars = sorted(r["chars"])[len(r["chars"]) // 2] if r["chars"] else "—"
        click.echo(
            f"{arm['key']:<14} {r['ok']}/{r['calls']:>3} {p50 or '—':>7} {p95 or '—':>7} "
            f"{chars:>6}  {arm['why']}" + (f"  [last fail: {r['last_fail']}]" if r["last_fail"] else "")
        )

    click.echo("\nverdict:")
    healthy = [
        (a, _pctl(sorted(results[a["key"]]["lat"]), 0.5))
        for a in arms
        if results[a["key"]]["ok"] == results[a["key"]]["calls"] and results[a["key"]]["lat"]
    ]
    if not healthy or baseline_p50 is None:
        click.echo("  baseline itself was unhealthy — judge nothing from this run; "
                   "the model is misbehaving, not mis-tuned.")
        return
    best, best_p50 = min(healthy, key=lambda t: t[1])
    delta = (baseline_p50 - best_p50) / baseline_p50 if baseline_p50 else 0
    if best["key"] == "baseline" or delta < 0.2:
        click.echo(
            f"  no knob beats baseline by more than ~20% ({repeat} rounds is noisy below that). "
            "The settings are not the problem — if doors still feel slow, it's the model: "
            "`flask bench-models --all-free` and pin a faster one as the page override."
        )
    else:
        click.echo(
            f"  {best['key']} wins: p50 {best_p50}ms vs baseline {baseline_p50}ms "
            f"(−{delta:.0%}). Worth applying: {best['why']}."
        )


def init_app(app) -> None:
    app.cli.add_command(send_due_emails_command)
    app.cli.add_command(housekeeping_command)
    app.cli.add_command(make_admin_command)
    app.cli.add_command(model_status_command)
    app.cli.add_command(bench_models_command)
    app.cli.add_command(refresh_chain_command)
    app.cli.add_command(warm_cache_command)
    app.cli.add_command(diagnose_doors_command)
    app.cli.add_command(bench_experiments_command)
