# Curio v1 — API contract

The frontend is a fat client: **all UI state (trail, tree, current page) lives in the
browser.** The backend is thin — it generates text, persists what the user chose to
keep, and sends email. Every response is JSON. Errors are
`{"error": "<machine_code>", "message": "<human text>"}` with a real HTTP status.

## A deliberate deviation from the handoff brief

The brief sketched a single `POST /api/generate {system, user}` passthrough. This
implementation uses **intent-based endpoints** instead (`/api/page`, `/api/seeds`, …),
with the prompts held server-side. Two reasons:

1. **Abuse.** Signup is open and the Pi is publicly reachable. A `{system, user}`
   passthrough is an open LLM relay — anyone could point a script at it and burn the
   shared free-model quota on unrelated work. Intent endpoints only ever emit Curio's
   own prompts.
2. **Prompt taste is the main quality dial**, and the brief wants it tuned *per model*.
   Server-side prompts mean tuning ships without rebuilding and redeploying the
   frontend.

The internals are unchanged: every endpoint below funnels into one `llm.generate()`
that applies the fallback chain, tolerant parsing, and stats logging. **One LLM call
per tap remains law.**

---

## Generation

All generation endpoints are rate-limited (per-IP for anonymous, per-user daily cap for
signed-in) and return `429` with `{"error":"quota"}` when a cap is hit.

### `POST /api/seeds`
Home doors, and the shuffle pool restock.

```jsonc
// request
{ "count": 4, "exclude": ["labels already shown"] }
// response
{ "seeds": [ { "label": "Why do we dream?", "type": "question" } ] }
```
`type` is always one of `fact` | `question` | `topic`.

### `POST /api/seeds/topical`
Doors adjacent to the signed-in user's saved interests (the "things you're
curious about" row on Home). Requires login. Same request/response shape as
`/api/seeds` (`count` defaults to 6). The interests are read from the user's
email preferences **server-side** — the client never sends them, and the wire
carries only the generated labels. When no topics are saved, responds
`{"seeds": []}` without generating anything, and therefore without touching
the quota — quota counts generations, not requests.

### `POST /api/more/stream` and `POST /api/ask/stream`
Streaming variants of `/api/more` and `/api/ask` (same request bodies). The
response is `text/event-stream`: unnamed events carry JSON-encoded prose
chunks, a final `done` event ends the answer, and an `error` event means the
stream failed — clients should retry once against the JSON endpoint. The
model fallback chain operates only *before* the first token (switching models
mid-answer would splice two different answers); rate limiting is identical to
the JSON endpoints. Only these two intents stream: they are single prose
fields, whereas a page is structured JSON that is useless until complete.

### `POST /api/page/stream`
Streaming door-open (same request body as `/api/page`). Unnamed SSE events
carry the **blurb's** text as the model writes it — plucked live out of the
JSON the model is emitting, cosmetic only; `done` carries the authoritative
full `{title, blurb, buttons}` parsed from the complete reply; `error` means
fall back to `/api/page`. Cache and quota semantics are identical to
`/api/page` — a cache hit is a single immediate `done` and costs nothing.

### `POST /api/page`
The core call — at most one generation per tap. Non-surprise pages are served
from a server-side cache when the same `(label, kind)` was generated in the
last week; a hit involves no model call and **deliberately bypasses the
quota** (which exists to protect the shared free-model budget — a SQLite read
spends none of it, so the cache check runs before the rate-limit gate; don't
"fix" the ordering). Cached pages ignore `path` context. `surprise` pages are
never cached in either direction.

```jsonc
// request
{
  "label": "Why do we dream?",   // null when surprise=true
  "kind":  "question",
  "path":  ["Sleep", "REM"],     // recent trail titles; server caps at last 4
  "surprise": false,             // wildcard door
  "exclude": ["titles to avoid"] // only meaningful when surprise=true
}
// response
{
  "title": "Why do we dream?",
  "blurb": "Two vivid, accurate sentences…",
  "buttons": [ { "label": "…", "type": "fact" } ]   // exactly 5
}
```

### `POST /api/more`
"Tell me more" — appends a deeper paragraph.

```jsonc
{ "title": "Why do we dream?", "said": "everything the page has said so far" }
// → { "more": "3-4 sentences" }
```

### `POST /api/ask`
Inline follow-up Q&A.

```jsonc
{ "title": "…", "said": "…", "question": "But what about lucid dreams?" }
// → { "answer": "2-4 sentences" }
```

### `POST /api/recap`
"Close the wander".

```jsonc
{ "path": ["title", "title", "title"] }
// → { "synthesis": "3 sentences", "thread": "one open question" }
```

---

## Auth

Session cookie (Flask-Login), `HttpOnly` + `SameSite=Lax`, `Secure` in production.
Passwords hashed with argon2. Signup is open, rate-limited per IP.

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/auth/signup` | `{email, password}` → `{user}`; 409 if taken |
| `POST` | `/api/auth/login` | `{email, password}` → `{user}`; 401 on bad creds |
| `POST` | `/api/auth/logout` | → `{ok: true}` |
| `GET`  | `/api/auth/me` | → `{user}` or `{user: null}` — never 401 |

`user` is `{id, email, role}` where `role` is `admin` | `user`.

**Anonymous use is allowed.** A signed-out visitor can wander freely; nothing
persists. This keeps the artifact's "tap a door immediately" feel intact. Signing in
is what buys durability.

---

## Persistence (signed-in only; `401` otherwise)

The client owns the tree and assigns each node a `clientNodeId`. The server mirrors it
into rows and returns its own `id`, which the client stores as `serverId`.

| Method | Path | Body → Response |
|---|---|---|
| `POST` | `/api/wanders` | `{}` → `{id, startedAt}` |
| `GET` | `/api/wanders` | → `{wanders: [{id, startedAt, closedAt, pageCount, firstTitle, lastTitle}]}` |
| `GET` | `/api/wanders/:id` | → `{id, startedAt, closedAt, recap, pages: [page]}` |
| `POST` | `/api/wanders/:id/pages` | `{clientNodeId, parentClientNodeId, kind, title, blurb, buttons}` → `{id}` |
| `PATCH` | `/api/pages/:id` | `{more?: [...], qa?: [...]}` → `{ok}` |
| `POST` | `/api/wanders/:id/close` | `{recap: {path, synthesis, thread}}` → `{ok}` |
| `GET` | `/api/saves` | → `{saves: [page]}` |
| `POST` | `/api/saves` | `{pageId}` → `{ok}` |
| `DELETE` | `/api/saves/:pageId` | → `{ok}` |

A persisted `page` is
`{id, wanderId, parentId, clientNodeId, parentClientNodeId, kind, title, blurb, more, qa, buttons, createdAt}`.

### `GET /api/resume` — the return hook
```jsonc
{ "wander": { "id": 12, "lastTitle": "The color that used to be poisonous", "pageCount": 7 },
  "door":   { "label": "…", "type": "topic" } }
```
Either field may be `null`. This is an invitation, not a nag — the UI shows it once,
quietly, and never counts days or breaks streaks.

---

## Admin (`role == "admin"` only; `403` otherwise)

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/admin/models` | OpenRouter catalogue filtered to `:free`, joined with this app's recent success-rate/latency stats |
| `GET` | `/api/admin/config` | → `{chain: ["model-a", "model-b"], overrides: {page: "model-c"}}` |
| `PUT` | `/api/admin/config` | same shape; takes effect immediately, no restart |
| `POST` | `/api/admin/test` | `{model, intent}` → `{ok, raw, parsed, latencyMs, error}` — vets a free model's JSON discipline |
| `GET` | `/api/admin/stats` | per-model rollup: calls, ok-rate, p50/p95 latency, last error |

---

## Email

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/email-prefs` | → prefs for current user |
| `PUT` | `/api/email-prefs` | `{enabled, topics: [], wildcard, sendHour, frequency, timezone}` |
| `GET` | `/unsub/:token` | one-click, no login, honored instantly |
| `GET` | `/d/:token` | deep link from an email — redirects to `/?door=:token` |
| `GET` | `/api/door/:token` | exchanges that token for `{label, type}` so the client can open the page |

`frequency` is `daily` | `weekdays` | `weekly`. Users who configure nothing get
nothing. No open tracking, no re-engagement copy, no escalating frequency.

`timezone` is the browser's IANA zone (e.g. `America/New_York`), sent silently
on save; `sendHour` is interpreted on that clock. Unknown zones store `''` and
fall back to the server's `CURIO_DEFAULT_TZ`.
