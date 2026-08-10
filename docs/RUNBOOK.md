# Curio runbook

What is deployed, where it lives, and what to do when something looks wrong.
`DEPLOY.md` is how it got here; this is how to live with it.

## What is running

| Piece | Where | Notes |
|---|---|---|
| Curio service | `curio.service` (systemd) | waitress, 4 threads, `127.0.0.1:5000`, capped at 200MB |
| Frontend | `frontend/dist/`, served by Flask | committed prebuilt; the Pi never runs npm |
| Database | `/home/io/curio/curio.db` | SQLite, WAL |
| Public access | Tailscale Funnel → `127.0.0.1:5000` | permanent hostname, TLS at the edge |
| Email | Gmail SMTP, app password, port 465 | hourly cron decides who is due |
| Scheduled jobs | user crontab, see `deploy/crontab.example` | email, housekeeping, backup, chain repair |
| Backups | `/home/io/curio/backups/`, 14 days | nightly, gzipped, online-backup API |

Config lives in `backend/.env` (mode 600) and nowhere else. It beats the
ambient environment — see `config.py` for why that is deliberate.

## Everyday checks

```bash
systemctl status curio                        # is it up
journalctl -u curio -n 50 --no-pager          # what it has been saying
systemctl show curio -p MemoryCurrent         # against the 200M cap
cd ~/curio/backend && .venv/bin/flask model-status --days 7
tail -5 ~/curio/logs/*.log                    # cron jobs
ls -lh ~/curio/backups | tail -3              # backups are landing
```

## When something is wrong

**Pages fail to generate.** Almost always the model chain, not the code. The
free catalogue retires models without notice.
```bash
.venv/bin/flask bench-models --all-free       # what still works
.venv/bin/flask refresh-chain --force         # adopt the fastest survivors
```

**No email arrived.** Check in this order: the user has preferences saved at
all, `CURIO_MAIL_DRY_RUN=0`, then the log.
"Send around" runs on each user's own clock (browser-reported timezone,
`CURIO_DEFAULT_TZ` as the fallback) — an email that arrives hours off means
the user's stored timezone is empty and the default is wrong for them; they
can fix it by simply re-saving Settings.
```bash
tail -20 ~/curio/logs/email.log
.venv/bin/flask send-due-emails --user-id 1   # ignores the schedule
```
`skipped` means nobody was due — that is not a failure.

**The service will not start.**
```bash
journalctl -u curio -n 80 --no-pager
bash ~/curio/deploy/smoke.sh                  # boots it by hand, plainer errors
```

**The site is unreachable but the service is up.** That is Funnel, not Curio.
```bash
tailscale funnel status
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5000/healthz   # 200 = app fine
```

**Restore a backup.**
```bash
sudo systemctl stop curio
gunzip -c ~/curio/backups/curio-YYYYMMDD-HHMMSS.db.gz > ~/curio/curio.db
sudo systemctl start curio
```

## Deploying a change

```bash
cd ~/curio && git pull
cd backend && .venv/bin/pip install -r requirements.txt   # only if deps changed
.venv/bin/python -m pytest tests -q
sudo systemctl restart curio
```

Frontend changes must be built off the Pi and committed — see `DEPLOY.md` §3.

## Known limits

- **Signup is open and the host is public.** The caps in `.env`
  (`CURIO_DAILY_CAP_USER`, `CURIO_DAILY_CAP_ANON_IP`, `CURIO_SIGNUP_CAP_IP`) are
  the only thing stopping one visitor draining the shared free-model quota.
- **Nothing watches the watcher.** If `curio.service` dies in a way systemd
  cannot restart, the first sign is the site being down. There is no alerting.
- **Backups sit on the same SD card as the database.** They survive a bad
  restore or a bad migration; they do not survive the card failing. Copying
  `backups/` off the Pi periodically is worth doing.
- **Free models are the slow tier.** Multi-second page loads are the
  architecture, not a bug. Streaming is the deferred fix.
- **No grounding or citations.** Pages are model output, presented as such.

## Deferred, in rough order of value

1. **Streaming responses** — the largest felt-quality win; makes generation feel
   fast without being faster.
2. **Server-side caching of popular pages** — cuts quota use and latency for
   anything already walked.
3. **Real grounding / citations** via a retrieval layer. The prototype tried
   doing this inside the generation call and it produced truncated JSON; it
   needs to be its own step.
