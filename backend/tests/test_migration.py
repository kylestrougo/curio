"""Columns added after first deploy must reach databases that already exist.

schema.sql is all CREATE TABLE IF NOT EXISTS, which does nothing to a table
that is already there — so every column added post-launch goes through
db._ensure_column at boot. These tests build a database with the ORIGINAL
shape and assert that starting the app upgrades it.
"""
import os
import sqlite3
import tempfile

import pytest

from curio import create_app
from curio.config import Config

# Tables exactly as they shipped, before the post-launch columns existed
# (email_prefs.timezone, page_cache.terms_json).
_V1_EMAIL_PREFS = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE email_prefs (
    user_id     INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    enabled     INTEGER NOT NULL DEFAULT 0,
    topics_json TEXT    NOT NULL DEFAULT '[]',
    wildcard    INTEGER NOT NULL DEFAULT 1,
    send_hour   INTEGER NOT NULL DEFAULT 8,
    frequency   TEXT    NOT NULL DEFAULT 'daily'
                CHECK (frequency IN ('daily', 'weekdays', 'weekly')),
    unsub_token TEXT    NOT NULL UNIQUE,
    last_sent_on TEXT
);
CREATE TABLE page_cache (
    cache_key    TEXT PRIMARY KEY,
    label        TEXT NOT NULL,
    kind         TEXT NOT NULL,
    title        TEXT NOT NULL,
    blurb        TEXT NOT NULL,
    buttons_json TEXT NOT NULL,
    model        TEXT,
    hits         INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@pytest.fixture()
def old_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.executescript(_V1_EMAIL_PREFS)
    conn.execute(
        "INSERT INTO users (email, password_hash) VALUES ('old@example.com', 'x')"
    )
    conn.execute(
        "INSERT INTO email_prefs (user_id, enabled, unsub_token) VALUES (1, 1, 'tok')"
    )
    conn.commit()
    conn.close()
    yield path
    os.unlink(path)


def _columns(path, table):
    conn = sqlite3.connect(path)
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    conn.close()
    return cols


def test_boot_adds_timezone_to_an_existing_database(old_db_path):
    assert "timezone" not in _columns(old_db_path, "email_prefs")

    class Cfg(Config):
        DATABASE = old_db_path
        SECRET_KEY = "test-secret"
        TESTING = True

    create_app(Cfg)  # boot runs init_db, which runs the guarded ALTERs
    assert "timezone" in _columns(old_db_path, "email_prefs")
    assert "terms_json" in _columns(old_db_path, "page_cache")

    # Existing rows got the empty default (→ server default zone), unharmed.
    conn = sqlite3.connect(old_db_path)
    row = conn.execute("SELECT enabled, timezone FROM email_prefs").fetchone()
    conn.close()
    assert row == (1, "")


def test_boot_is_idempotent_on_a_current_database(old_db_path):
    class Cfg(Config):
        DATABASE = old_db_path
        SECRET_KEY = "test-secret"
        TESTING = True

    create_app(Cfg)
    create_app(Cfg)  # second boot must not fail on the existing column
    assert "timezone" in _columns(old_db_path, "email_prefs")
