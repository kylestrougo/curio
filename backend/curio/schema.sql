-- Curio v1 schema. SQLite, WAL mode, single file.
-- The spine is wanders → pages(parent_id), which mirrors the client's tree 1:1.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS wanders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    started_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    closed_at   TEXT,
    recap_json  TEXT
);
CREATE INDEX IF NOT EXISTS idx_wanders_user ON wanders(user_id, started_at DESC);

-- parent_id is a self-reference: this table IS the trail map.
-- client_node_id lets the fat client reconcile its in-memory tree with our rows.
CREATE TABLE IF NOT EXISTS pages (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    wander_id             INTEGER NOT NULL REFERENCES wanders(id) ON DELETE CASCADE,
    parent_id             INTEGER REFERENCES pages(id) ON DELETE CASCADE,
    client_node_id        INTEGER,
    parent_client_node_id INTEGER,
    kind                  TEXT,
    title                 TEXT NOT NULL,
    blurb                 TEXT NOT NULL DEFAULT '',
    more_json             TEXT NOT NULL DEFAULT '[]',
    qa_json               TEXT NOT NULL DEFAULT '[]',
    buttons_json          TEXT NOT NULL DEFAULT '[]',
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pages_wander ON pages(wander_id, id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pages_client_node
    ON pages(wander_id, client_node_id) WHERE client_node_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS saved_pages (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    page_id    INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, page_id)
);

CREATE TABLE IF NOT EXISTS app_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS email_prefs (
    user_id     INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    enabled     INTEGER NOT NULL DEFAULT 0,
    topics_json TEXT    NOT NULL DEFAULT '[]',
    wildcard    INTEGER NOT NULL DEFAULT 1,
    send_hour   INTEGER NOT NULL DEFAULT 8,       -- hour 0-23 on the user's own clock
    frequency   TEXT    NOT NULL DEFAULT 'daily'
                CHECK (frequency IN ('daily', 'weekdays', 'weekly')),
    unsub_token TEXT    NOT NULL UNIQUE,
    last_sent_on TEXT,                             -- LOCAL date only; the send-once-a-day guard
    -- IANA zone captured from the browser on settings save ('' = unknown,
    -- fall back to CURIO_DEFAULT_TZ). Without this, send_hour was compared
    -- against the UTC clock and "send around 11pm" meant 7pm in New York.
    timezone    TEXT    NOT NULL DEFAULT ''
);

-- Deep links from the daily email. The token is opaque so an email address
-- can't be enumerated from a URL; generation happens on arrival.
CREATE TABLE IF NOT EXISTS door_tokens (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
    label      TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'topic',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One tap of the share button, frozen. The link shows exactly this page —
-- title, blurb, any tell-me-more and Q&A — to anyone, with no LLM call.
CREATE TABLE IF NOT EXISTS shared_pages (
    token        TEXT PRIMARY KEY,
    user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
    kind         TEXT,
    title        TEXT NOT NULL,
    blurb        TEXT NOT NULL DEFAULT '',
    more_json    TEXT NOT NULL DEFAULT '[]',
    qa_json      TEXT NOT NULL DEFAULT '[]',
    buttons_json TEXT NOT NULL DEFAULT '[]',
    terms_json   TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Which free models are actually behaving this week. Drives the admin page.
CREATE TABLE IF NOT EXISTS model_stats (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    model      TEXT    NOT NULL,
    intent     TEXT    NOT NULL,
    ok         INTEGER NOT NULL,
    latency_ms INTEGER,
    error      TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_model_stats_recent ON model_stats(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_stats_model ON model_stats(model, created_at DESC);

-- Generation accounting: protects the shared free-model quota from one heavy
-- user (or one script) starving everyone else.
CREATE TABLE IF NOT EXISTS usage_counters (
    subject TEXT NOT NULL,       -- 'user:12' or 'ip:1.2.3.4'
    day     TEXT NOT NULL,       -- YYYY-MM-DD (UTC)
    count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (subject, day)
);

-- Generated pages, cached by what was tapped. A hit skips the LLM entirely —
-- this is the sanctioned answer to slow doors (handoff: "server-side caching
-- of popular pages"), where speculative client prefetch is not. Content is
-- only ever written from a successful server-side generation; `model` exists
-- so a misbehaving model's pages can be purged in one statement.
CREATE TABLE IF NOT EXISTS page_cache (
    cache_key    TEXT PRIMARY KEY,               -- lower(trim(label)) || ':' || kind
    label        TEXT NOT NULL,
    kind         TEXT NOT NULL,
    title        TEXT NOT NULL,
    blurb        TEXT NOT NULL,
    buttons_json TEXT NOT NULL,
    terms_json   TEXT NOT NULL DEFAULT '[]',    -- tap-to-wander terms inside the blurb
    model        TEXT,                           -- NULL when the live path didn't note it
    hits         INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
