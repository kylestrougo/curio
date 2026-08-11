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

**Pages read confidently wrong** (invented events, made-up terminology).
Generation runs at a low temperature and the prompts forbid invention, but
those only narrow the odds — the model itself is the biggest lever. Run
`bench-models`, read a few pages from each survivor by hand via the /admin
test button, and pin the strongest as the `page` override in /admin config.
The rest of the chain still backs it up if it goes down.

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
- **Free models are the slow tier.** A *fresh* page still takes multi-second
  generation. The page cache absorbs the common cases: any door tapped in the
  last week opens instantly, and `warm-cache` pre-generates the starter doors
  nightly. Cache hits don't count against anyone's quota.
  To purge a misbehaving model's cached pages:
  `sqlite3 ~/curio/curio.db "DELETE FROM page_cache WHERE model = 'bad/model:free'"`
  (or simply wait out the 7-day TTL).
- **No grounding or citations.** Pages are model output, presented as such.

## Deferred, in rough order of value

1. ~~Streaming responses~~ — **done for "tell me more" and Q&A** (the prose
   intents; tokens render as they arrive, with the JSON endpoints as
   fallback). Page streaming stays deferred: a page is structured JSON,
   useless until nearly complete, and streaming it means a wire-format
   change plus re-vetting every model in the chain.
   *Caveat:* streamed delivery through Tailscale Funnel should be verified
   once (`curl -N` against the public URL and watch tokens trickle); if
   Funnel buffers, the UI silently degrades to whole-answer delivery.
2. ~~Server-side caching of popular pages~~ — **done**: `page_cache` table,
   quota-free hits, nightly `warm-cache`, 7-day TTL via housekeeping.
3. **Real grounding / citations** via a retrieval layer. The prototype tried
   doing this inside the generation call and it produced truncated JSON; it
   needs to be its own step.
