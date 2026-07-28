# Curio

*A curiosity engine. Tap a door, land on a page, tap wherever curiosity pulls — and
wander a tree of your own choosing.*

Curio sits deliberately between two things. Social media is pure **push**: the
algorithm decides, optimising for time-on-app. A search box is pure **pull**: all the
intentionality is yours, including the hard part of knowing where to start.

Curio's principle is **push to ignite, pull to explore** — the app supplies the spark,
you steer everything after, both the direction and the depth.

There are no streaks, no notifications, no engagement dark patterns, and nothing in
here is designed to keep you here longer than you want to be.

---

## What it does

- **Doors.** Home offers a few tappable hooks across different domains, plus a
  wildcard and a free-text box if you'd rather start somewhere of your own.
- **Pages.** Each tap opens a short blurb and ~5 next steps — a mix of surprising
  facts, provocative questions, and adjacent topics.
- **Depth on demand.** "Tell me more" goes a level deeper, as many times as you like.
  Inline follow-up Q&A answers anything the page raised.
- **A trail, and a map.** Breadcrumbs for where you are; a tree view of every branch
  you walked. Your map, not an algorithm's.
- **Closing the wander.** When *you* decide you're done, Curio names the thread that
  connected the walk and hands you one open question to carry into tomorrow.

## Architecture

```
frontend/   Vite + React, built to static files. Fat client — all UI state lives here.
backend/    One small Flask service. SQLite (WAL). Talks to OpenRouter over HTTPS.
deploy/     systemd unit, cron jobs, SQLite backup script.
docs/       API contract, deployment guide, product brief, original prototype.
```

Deliberately small: no ORM, no agent framework, no Node at runtime, no Postgres, no
in-process scheduler. It targets a Raspberry Pi 3 with 1GB of RAM that is already
running several other services, at ~$0/month.

**One LLM call per tap is law.** An earlier prototype tried prefetching the next five
pages and hit an immediate rate-limit stampede. See `docs/handoff-v2.md` for the
other things tried and reverted.

### The free-model problem

Generation runs on OpenRouter's free models, which churn constantly, have daily caps,
and vary wildly in JSON discipline and latency. The backend is built around that:

- An **ordered fallback chain** — on a transport error, a rate limit, or two
  consecutive unparseable responses, it falls through to the next model.
- **Tolerant parsing** that recovers JSON from code fences, chatty preambles,
  trailing commas, smart quotes, and unescaped newlines.
- **Per-model stats** logged on every call, so `/admin` can show which free models
  are actually behaving this week — and the chain is reorderable live, no restart.

## Running it locally

**Backend**
```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env      # set OPENROUTER_API_KEY; CURIO_COOKIE_SECURE=0 for http
.venv/bin/python wsgi.py  # → http://127.0.0.1:5000
```

**Frontend**
```bash
cd frontend
npm install
npm run dev               # → http://localhost:5173, proxies /api to Flask
```

**Tests**
```bash
cd backend && .venv/bin/python -m pytest tests -q
```

Deployment to the Pi is in [`docs/DEPLOY.md`](docs/DEPLOY.md). The API contract —
including one deliberate deviation from the original brief and why — is in
[`docs/API.md`](docs/API.md).

## Privacy

Your wanders are yours. There is no analytics, no tracking pixel in the daily email,
no click tracking on its links, and no third party gets your trail. The only outbound
call is the generation request to OpenRouter, which sees the prompt but not your
identity.
