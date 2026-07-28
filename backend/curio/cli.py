"""CLI commands. Cron calls these — no long-lived scheduler process.

Keeping the scheduler out of the Flask process is deliberate: an APScheduler
thread would sit in memory all day on a Pi 3 that's already running several
services. `cron` costs nothing when it isn't running.
"""
from __future__ import annotations

import click
from flask.cli import with_appcontext

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
    click.echo(f"pruned {counters} rate-limit counters; stats and door tokens older than 30d removed")


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


def init_app(app) -> None:
    app.cli.add_command(send_due_emails_command)
    app.cli.add_command(housekeeping_command)
    app.cli.add_command(make_admin_command)
    app.cli.add_command(model_status_command)
    app.cli.add_command(bench_models_command)
    app.cli.add_command(refresh_chain_command)
