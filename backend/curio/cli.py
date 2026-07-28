"""CLI commands. Cron calls these — no long-lived scheduler process.

Keeping the scheduler out of the Flask process is deliberate: an APScheduler
thread would sit in memory all day on a Pi 3 that's already running several
services. `cron` costs nothing when it isn't running.
"""
from __future__ import annotations

import click
from flask import current_app
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
    stats = execute("DELETE FROM model_stats WHERE created_at < datetime('now', '-30 days')")
    tokens = execute("DELETE FROM door_tokens WHERE created_at < datetime('now', '-30 days')")
    click.echo(f"pruned counters={counters} (stats and tokens older than 30d also removed)")


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


def init_app(app) -> None:
    app.cli.add_command(send_due_emails_command)
    app.cli.add_command(housekeeping_command)
    app.cli.add_command(make_admin_command)
    app.cli.add_command(model_status_command)
