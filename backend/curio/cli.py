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


@click.command("bench-models")
@click.option("--models", default=None, help="Comma-separated model ids. Defaults to the current chain.")
@click.option("--all-free", is_flag=True, help="Benchmark every free model in the catalogue (slow).")
@click.option("--repeat", type=int, default=1, help="Calls per model; median is reported.")
@with_appcontext
def bench_models_command(models, all_free, repeat):
    """Time the free models on a real page generation and check the JSON contract.

    Deliberately sequential. Firing these in parallel is how you trip the free
    tier's rate limits and end up benchmarking 429s instead of models.
    """
    from statistics import median

    from .llm import generate_raw, list_free_models
    from . import prompts

    if models:
        ids = [m.strip() for m in models.split(",") if m.strip()]
    elif all_free:
        ids = [m["id"] for m in list_free_models()]
    else:
        ids = get_chain()
    if not ids:
        click.echo("Nothing to benchmark.")
        return

    system, user = prompts.page("Why do we dream?", "question", [], False, [])
    est = len(ids) * repeat * 12
    click.echo(f"{len(ids)} model(s) × {repeat} — roughly {est // 60}m{est % 60:02d}s if all respond\n")

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
            click.echo(f"  ✗ {mid} — {failure}")
            results.append((None, mid, failure))
        else:
            ms = int(median(latencies))
            click.echo(f"  ✓ {mid} — {ms}ms")
            results.append((ms, mid, None))

    good = sorted([r for r in results if r[0] is not None])
    click.echo("\n── usable, fastest first ──")
    if not good:
        click.echo("None passed. Try --all-free, or check the key and quota.")
        return
    for ms, mid, _ in good:
        click.echo(f"{ms:>7}ms  {mid}")
    click.echo("\nSuggested chain (paste into /admin, or CURIO_MODEL_CHAIN):")
    click.echo(",".join(mid for _, mid, _ in good[:3]))


def init_app(app) -> None:
    app.cli.add_command(send_due_emails_command)
    app.cli.add_command(housekeeping_command)
    app.cli.add_command(make_admin_command)
    app.cli.add_command(model_status_command)
    app.cli.add_command(bench_models_command)
