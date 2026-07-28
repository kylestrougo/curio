# Deploying Curio to the Pi

Target from the brief: Pi 3, 1GB RAM, already running OpenClaw, a Flask blog and a
StreetEasy monitor. Tailscale + Cloudflare Tunnel available. ~$0 running cost.

The whole thing is one Python process plus a directory of static files. Nothing
heavyweight runs locally — the LLM layer is plain HTTPS calls to OpenRouter.

## 1. Get the code onto the Pi

```bash
git clone <this repo> /home/pi/curio
cd /home/pi/curio
```

## 2. Backend

```bash
cd /home/pi/curio/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env
# Fill in at minimum: OPENROUTER_API_KEY, CURIO_PUBLIC_URL, CURIO_ADMIN_EMAIL.
# For email: CURIO_SMTP_USER + CURIO_SMTP_PASSWORD (Gmail app password).
$EDITOR .env
```

The database is created automatically on first boot. To do it by hand:
`.venv/bin/flask init-db`.

## 3. Frontend

Building Vite on a Pi 3 is slow but works. Building on your laptop and copying
`frontend/dist/` across is faster.

```bash
cd /home/pi/curio/frontend
npm ci
npm run build     # → frontend/dist
```

Point `CURIO_STATIC_DIR` at that `dist` directory. Flask serves it directly, so
the Pi doesn't need a second web server in front of Curio.

## 4. systemd

```bash
sudo cp /home/pi/curio/deploy/curio.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now curio
systemctl status curio
journalctl -u curio -f
```

The unit sets `MemoryMax=200M`. Waitress with 4 threads should sit far below that —
if it doesn't, something is wrong; investigate rather than raising the cap.

## 5. Cloudflare Tunnel

Add an ingress rule to your existing tunnel config pointing your hostname at
`http://127.0.0.1:5000`:

```yaml
ingress:
  - hostname: curio.example.com
    service: http://127.0.0.1:5000
  # … your existing services …
  - service: http_status:404
```

Then `sudo systemctl restart cloudflared`.

Make sure `CURIO_PUBLIC_URL` matches the public hostname — it's used for email
links and the OpenRouter attribution header. Keep `CURIO_COOKIE_SECURE=1`; the
tunnel terminates TLS, so cookies are travelling over HTTPS.

## 6. Cron

```bash
mkdir -p /home/pi/curio/logs /home/pi/curio/backups
crontab -e   # paste from deploy/crontab.example
```

The email job runs hourly and decides for itself who is due — that's how a user
who picked 07:00 gets it at 07:00 while nobody receives two in a day.

## 7. First run

1. Visit the site and sign up with the address in `CURIO_ADMIN_EMAIL`. That first
   account is promoted to admin automatically. (Missed it? `flask make-admin you@example.com`.)
2. Go to `/admin`. The free-model list loads from OpenRouter.
3. Use **test generation** on a few models against the `page` intent — that's the
   fastest way to see which ones actually respect the JSON contract.
4. Set the fallback chain to ~3 that behaved. Save. It takes effect immediately.
5. Wander a bit, then check `flask model-status` to see real success rates.

## Operating notes

**Which free models are working?**
```bash
cd /home/pi/curio/backend && .venv/bin/flask model-status --days 7
```
The free list churns constantly. When one starts failing, reorder the chain from
`/admin` — no restart, no deploy.

**Test the email without waiting for cron:**
```bash
.venv/bin/flask send-due-emails --user-id 1     # ignores the schedule
# Set CURIO_MAIL_DRY_RUN=1 first to print instead of send.
```

**Restore a backup:**
```bash
sudo systemctl stop curio
gunzip -c /home/pi/curio/backups/curio-YYYYMMDD-HHMMSS.db.gz > /home/pi/curio/curio.db
sudo systemctl start curio
```

**Memory check:**
```bash
systemctl show curio -p MemoryCurrent
```

## Things deliberately not done

- **No Postgres.** SQLite in WAL mode is correct at this scale; the brief says so
  and it's right.
- **No Node at runtime.** Vite is a build-time dependency only.
- **No in-process scheduler.** cron, so nothing sits in RAM between runs.
- **No client-side prefetching.** The prototype tried it and hit a rate-limit
  stampede. One LLM call per tap remains law.
