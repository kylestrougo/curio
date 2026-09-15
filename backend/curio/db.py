"""SQLite access. stdlib sqlite3, no ORM — this has to be light on a Pi 3."""
import sqlite3
from pathlib import Path

import click
from flask import current_app, g

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,
            timeout=15,
        )
        conn.row_factory = sqlite3.Row
        # WAL lets the cron email job read while the web process writes.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(_e=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _ensure_column(db: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """Add a column to an existing table if it is missing.

    schema.sql is all CREATE TABLE IF NOT EXISTS, which does nothing for a
    database that already exists — so a column added there never reaches a
    deployed Pi. This is the project's whole migration story: one guarded
    ALTER per added column, run at every boot, idempotent. If the migrations
    ever get more interesting than adding columns, that is the moment to adopt
    a real tool rather than grow this.
    """
    have = {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in have:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _once(db: sqlite3.Connection, flag: str) -> bool:
    """Claim a one-time data-migration flag in app_config.

    True only for the boot that wins the INSERT — every later boot (and every
    concurrent worker, thanks to SQLite's single-writer lock) sees the row and
    skips. The flag and the migration it guards share init_db's transaction.
    """
    cur = db.execute("INSERT OR IGNORE INTO app_config (key, value) VALUES (?, 'done')", (flag,))
    return cur.rowcount == 1


def init_db() -> None:
    db = get_db()
    db.executescript(SCHEMA_PATH.read_text())
    # Columns added after first deploy (see _ensure_column):
    _ensure_column(db, "email_prefs", "timezone", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(db, "page_cache", "terms_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(db, "wanders", "recap_saved", "INTEGER NOT NULL DEFAULT 0")
    # One-time data migrations, each behind a claimed flag (see _once).
    if _once(db, "migrated:email_on_by_default"):
        # Emails became opt-out: flip everyone on once, move the untouched
        # 8am default to 8pm, and give zone-less rows the Eastern default.
        # A user who disables afterwards is never re-flipped — the flag stays.
        db.execute("UPDATE email_prefs SET enabled = 1")
        db.execute("UPDATE email_prefs SET send_hour = 20 WHERE send_hour = 8")
        db.execute("UPDATE email_prefs SET timezone = 'America/New_York' WHERE timezone = ''")
    db.commit()


def query(sql: str, args=(), one: bool = False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    cur.close()
    return (rows[0] if rows else None) if one else rows


def execute(sql: str, args=()) -> int:
    """Run a write and commit. Returns lastrowid."""
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    last = cur.lastrowid
    cur.close()
    return last


@click.command("init-db")
def init_db_command() -> None:
    """Create tables if they don't exist. Safe to re-run."""
    init_db()
    click.echo("Initialised the database.")


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
