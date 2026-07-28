# Curio — Product Handoff Brief (v2)

*A curiosity engine. Working MVP prototype → now scoped for a self-hosted v1 on a Raspberry Pi. This doc + the current `curio.jsx` are everything Claude Code needs to continue. v2 supersedes the original brief; history is retained so decisions aren't relitigated blindly.*

---

## One-liner

A research-assistant companion that knows your interests and hands you one good door to walk through — the opposite of doomscrolling. You tap a topic, land on a short page, and tap wherever curiosity pulls, wandering a tree of your own choosing.

## Positioning

Curio sits deliberately between two things:

- **Social media** is pure *push* — the algorithm decides, optimizing for time-on-app.
- **A search box** (Google, Wikipedia, ChatGPT) is pure *pull* — all the intentionality is yours, including the hard part of knowing where to start.

Curio's principle is **push to ignite, pull to explore**: the app supplies the spark (a daily door), the user steers everything after — both the *direction* and the *depth* of engagement.

## Core loop

1. **Seed** — home shows a few tappable "doors" (hooks) across different domains.
2. **Tap** — user follows whatever pulls them.
3. **Page** — a short blurb plus ~5 tappable next steps (mix of facts, questions, topics).
4. **Wander** — repeat, Wikipedia-style, down a self-directed path; branch and backtrack freely.
5. **Deepen** — on any page: "Tell me more" (appends depth) and inline follow-up Q&A.
6. **Save + map** — save pages; a breadcrumb trail plus a **trail map** (tree view of every branch walked) make exploration feel intentional.
7. **Close** — user-initiated "Close the wander": a synthesis of the path plus one open question to carry into tomorrow.

## Product decisions already made (don't relitigate without reason)

- **Audience/scope:** universal — all topics, all people.
- **Session shape:** works for the 3-minute spark and the 40-minute rabbit hole.
- **The atomic unit (a "button"):** a *mix* of fact, question, and topic — color-coded (fact = slate, question = brass, topic = green).
- **Steering:** tap-the-buttons primarily, plus free-text "steer it yourself" on every page, plus per-page follow-up Q&A.
- **Signature element:** the trail + trail map. Your map, not an algorithm's.
- **Motivation lever:** resonant hooks + felt momentum. **No streaks, no notification pressure, no engagement dark patterns.** The daily email (new, below) must respect this: it's an invitation, not a hook — easy to configure, easy to silence.
- **Closing the wander is user-initiated.** The affordance appears quietly after 3+ pages; the app never declares a session over.
- **Citations: still deferred** to a later grounding milestone (see "What we tried and reverted").

## Current state of the artifact (`curio.jsx`)

Single-file React artifact, "reading room" aesthetic (warm paper, navy ink, brass accent, serif). All pages generated live by the LLM, one call per tap. Features as of handoff:

- Home with 4 doors; instant first paint from a local seed pool; generated doors fade in when ready.
- **Shuffle** with a self-refilling pool (background restock of novel doors when unseen supply < 8; one restock in flight at a time; recycles rather than ever blocking).
- **Surprise me** wildcard door (picks a topic from unexplored territory).
- Page view: blurb, **Tell me more** (repeatable depth), **follow-up Q&A** thread, 5 next-step doors, free-text steer, save.
- **Trail map**: session stored as a tree (`nodeId`/`parentId` on every page); tappable tree view with "you are here"; jumping rebuilds the linear trail root→node.
- **Recap**: "Close the wander" → path readback, 3-sentence synthesis naming the connecting thread, one "thread to carry" (itself a tappable door), keep-wandering / start-fresh.
- Robustness: request-id guard against stale in-flight responses on all navigation; `res.ok` checked with one quiet retry on 429/5xx; JSON fence-stripping + brace-extraction parse; prompt path context capped at last 4 steps; `max_tokens` 1000 (headroom — terse output is enforced by prompt, and a low cap was found to truncate JSON and break parsing).
- Saves are session-only (artifact limitation) — solved by persistence in v1 below.

## What we tried and reverted (keep honoring these lessons)

1. **Web search inside the generation call** → unparseable/truncated JSON. Grounding must be a proper retrieval layer, later milestone.
2. **Background citation fetch by page title** → blind, slow, low quality.
3. **Client-side prefetch of 5 next pages** → parallel-call stampede, rate limits. The self-refilling shuffle pool deliberately avoids this (single background call, gated).

**Standing lesson:** the critical path stays one LLM call per tap.

---

# v1 — "Curio, self-hosted" (NEW SCOPE)

Target: deployed on the Raspberry Pi (Pi 3, 1GB RAM — already running OpenClaw, a Flask blog, and a StreetEasy monitor; Tailscale + Cloudflare Tunnel available), publicly reachable via URL, multi-user, at ~$0 running cost.

## Architecture

- **Frontend:** the current `curio.jsx`, ported into a Vite React project, built to static files. Served by the existing web server (Flask static / Caddy) behind the existing Cloudflare Tunnel. Keep it a fat client: all UI state stays client-side; the backend is thin.
- **Backend:** one small Flask (or FastAPI) service on the Pi. Endpoints are simple JSON; no agent framework, no Node at runtime. This is deliberately Pi-3-friendly: the LLM layer is now plain HTTPS calls to OpenRouter, so nothing memory-heavy runs locally. (The earlier Agent-SDK-on-a-VM plan is obsolete for v1 — OpenRouter replaces it.)
- **Database:** SQLite, single file, WAL mode. Correct choice at this scale; do not introduce Postgres.
- **Scheduler:** system cron (or APScheduler inside the Flask process) for the daily emails. Prefer cron + a `flask send-due-emails` CLI command — no long-lived extra memory.
- **Ops:** systemd service like the other Pi services; logs to journald; DB backup = nightly copy of the SQLite file.

### LLM layer — OpenRouter free models

- All generation calls go through **one backend endpoint** (e.g. `POST /api/generate` with `{system, user}`); the frontend never talks to a provider directly and never sees the API key.
- Backend calls OpenRouter's OpenAI-compatible `POST /v1/chat/completions` with the currently configured model.
- **Free-model reality (design for it):** the free list churns; free models have daily request caps and highly variable JSON discipline and latency. Therefore:
  - Keep the artifact's tolerant JSON parsing (strip fences, extract outermost braces) server-side too; send `response_format: {type: "json_object"}` when the model supports it, but never rely on it.
  - Support an **ordered fallback chain**, not just one model: if the active model errors, rate-limits, or returns unparseable JSON twice, fall through to the next. (Open decision #3 below — confirm whether Kyle wants chain vs. single.)
  - Log per-model success/latency stats to a table so the admin page can show which free models are actually behaving this week.
- One call per tap remains law. Recap, tell-more, Q&A, and email generation are each single calls too.

### Admin page + model switcher

- Route `/admin`, visible only to the single admin profile.
- Fetches OpenRouter's `GET /models`, filters to `:free` variants, and lists them with context length + the app's own recent success-rate stats.
- Admin selects the **active model** (and fallback order, if chain is confirmed); saved to an `app_config` table; takes effect immediately, no restart.
- A "test generation" button that runs a sample page-generation and shows the raw + parsed result — the fastest way to vet a new free model's JSON behavior.
- Nice-to-have: per-feature model override (e.g. cheapest model for seed/email generation, best free model for pages).

### User profiles + persistence

- Roles: `admin` (exactly one) and `user`.
- Auth kept deliberately light for a self-hosted personal app — session cookie via Flask-Login, passwords hashed (argon2/bcrypt). Signup mode is Open decision #1.
- **What persists per user:**
  - **Wanders (threads):** the full session tree — every page (title, blurb, more[], qa[], buttons, kind, nodeId, parentId), so a wander can be reopened exactly, map and all. The artifact's tree structure maps 1:1 to rows; this is the schema's spine.
  - **Saved pages** (existing feature, now durable).
  - **The return hook:** last open wander surfaces on login as "you left off at ___" plus one fresh door. Invitation, not pressure.
- Sketch schema: `users`, `wanders` (id, user_id, started_at, closed_at, recap_json), `pages` (id, wander_id, parent_id, kind, title, blurb, more_json, qa_json, buttons_json, created_at), `saved_pages` (user_id, page_id), `app_config` (key, value), `email_prefs` (below), `model_stats`.

### Daily email — "doors for today"

- Per-user opt-in configuration: **topics of interest** (freeform list), an optional **"include a wildcard/random door"** toggle, send **time** and **frequency** (daily / weekdays / weekly), and one-click unsubscribe. Users who configure nothing get nothing.
- Content: 3–4 doors generated by the LLM from the user's topics (plus the wildcard if enabled), each a **deep link** that opens the app already on that page — requires a small route like `/d/<door-token>` that triggers generation on arrival. Optionally include the "thread to carry" from the user's last closed wander as one of the doors (nice continuity with the recap feature).
- Generation happens at send time via the same `/api/generate` path (counts against the free model's daily cap — batch all users in one cron run, one generation call per user).
- Delivery mechanism is Open decision #2. Note: Kyle already has a working Gmail-delivery pattern from the job-assistant pipeline on this same Pi — reuse is the low-friction path if Gmail SMTP is chosen.
- Anti-dark-pattern guardrails: no open tracking, no "we miss you" copy, no escalating frequency, unsubscribe honored instantly.

## Deployment steps (suggested order for Claude Code)

1. Port `curio.jsx` → Vite project; replace the in-artifact Anthropic `fetch` with `POST /api/generate`; verify feature parity locally.
2. Backend skeleton: `/api/generate` proxying OpenRouter with tolerant parsing + retry/fallback; `app_config` for model selection.
3. Admin page + model switcher + test button.
4. Auth + profiles; persistence of wanders/pages/saves; return hook on login.
5. Email prefs UI + cron sender + deep-link route.
6. systemd unit, Cloudflare Tunnel route, SQLite backup cron. Watch Pi memory: target < 80MB RSS for the Flask service; avoid heavy Python deps.
7. Later milestones unchanged from v1 thinking: streaming responses, server-side caching of popular pages, real grounding/citations via a retrieval layer.

## Open decisions

1. **Account creation: DECIDED — open self-signup.** Email + password, hashed, Flask-Login sessions. Since signup is public, add basic abuse guards: rate-limit the signup and generate endpoints per IP, and a per-user daily generation cap (protects the shared free-model quota from one heavy user starving everyone).
2. **Email delivery: DECIDED — Gmail SMTP with app password**, reusing the existing working pattern from the job-assistant pipeline on this same Pi. Keep sender volume modest (well under Gmail's ~500/day limit — a non-issue at this scale).
3. **Model config shape: DECIDED — active model + ordered fallback chain.** Admin sets an ordered list (~3 free models). Backend falls through to the next on error, rate limit, or two consecutive unparseable-JSON responses; failures are logged to `model_stats` so the admin page shows which models are misbehaving. Admin UI is a reorderable list, not a single dropdown.

## Open questions / things to tune (carried forward)

- **Prompt taste** remains the biggest quality dial — now also *per model*, since free models vary widely; the admin test button exists to tune this.
- **Seed quality** and the email doors share DNA — good hook-writing benefits both.
- **The ChatGPT defense** (current answer: presented + prompted discovery with a visible, intentional trail — direction and depth in the user's hands; now strengthened by the map, the recap, and the return hook).

## How to continue in Claude Code

1. Give it this brief + the current `curio.jsx`.
2. Say: "This is my Curio prototype and its v2 handoff brief — build the self-hosted v1 per the plan, starting at deployment step 1."
