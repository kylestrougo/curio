#!/usr/bin/env bash
# Boot Curio exactly as systemd will, prove it serves, then stop it again.
#
#   bash deploy/smoke.sh
#
# Nothing is installed and nothing keeps running: the server is started in the
# background, checked, and killed on the way out. Run this before enabling the
# systemd unit — a failure here is far easier to read than a restart loop.
#
# It deliberately makes no call to OpenRouter. That costs quota and deserves to
# be watched in a browser, so it happens later at /admin.

set -uo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
venv="$repo/backend/.venv"
port="${PORT:-5000}"
base="http://127.0.0.1:$port"
fails=0

ok()   { printf 'PASS  %s\n' "$1"; }
bad()  { printf 'FAIL  %s\n' "$1"; fails=$((fails+1)); }
note() { printf 'INFO  %s\n' "$1"; }

[ -x "$venv/bin/waitress-serve" ] || { echo "FAIL  no venv at $venv — run step 3 first"; exit 1; }
[ -f "$repo/backend/.env" ]       || { echo "FAIL  no backend/.env — run deploy/make-env.sh first"; exit 1; }

# The one config error that produces a confusing runtime failure rather than a
# clear one: an unset key means every generation 500s with no obvious cause.
if grep -qE '^OPENROUTER_API_KEY=.+' "$repo/backend/.env"; then
  ok "OPENROUTER_API_KEY is set"
else
  bad "OPENROUTER_API_KEY is empty in backend/.env — generation will fail"
fi

if ss -tln 2>/dev/null | grep -qE "[:.]$port\b"; then
  echo "FAIL  port $port is already in use — stop whatever holds it, or PORT=5001 bash deploy/smoke.sh"
  exit 1
fi

cleanup() {
  if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
    note "server stopped"
  fi
}
trap cleanup EXIT INT TERM

log="$(mktemp)"
cd "$repo/backend"
"$venv/bin/waitress-serve" --listen="127.0.0.1:$port" --threads=4 --call wsgi:build >"$log" 2>&1 &
pid=$!

# Boot on a Pi 3 is a couple of seconds; give it room but fail fast if the
# process dies outright.
for _ in $(seq 1 40); do
  if ! kill -0 "$pid" 2>/dev/null; then
    bad "server exited during startup"
    echo "──── output ────"; cat "$log"; rm -f "$log"; exit 1
  fi
  curl -fsS -o /dev/null "$base/healthz" 2>/dev/null && break
  sleep 0.5
done

code() { curl -s -o /dev/null -w '%{http_code}' "$1"; }

[ "$(code "$base/healthz")" = "200" ] && ok "/healthz responds" || bad "/healthz did not respond"

# The frontend is served by Flask itself; a 200 with html means CURIO_STATIC_DIR
# actually points at the committed bundle.
if curl -fsS "$base/" 2>/dev/null | grep -qi '<div id="root"'; then
  ok "frontend is being served"
else
  bad "frontend not served — check CURIO_STATIC_DIR in backend/.env"
fi

# Unauthenticated identity check: a signed-out caller should get a clean answer
# or a clean 401 — anything else means the auth stack did not wire up.
me="$(code "$base/api/auth/me")"
case "$me" in
  200|401) ok "/api/auth/me answers ($me)" ;;
  *)       bad "/api/auth/me returned $me" ;;
esac

db="$(grep -E '^CURIO_DB=' "$repo/backend/.env" | cut -d= -f2-)"
if [ -f "$db" ]; then
  ok "database created at $db"
  note "size: $(du -h "$db" | cut -f1)"
else
  bad "no database at $db"
fi

rss=$(ps -o rss= -p "$pid" 2>/dev/null | tr -d ' ')
[ -n "$rss" ] && note "resident memory: $((rss/1024))MB (unit caps at 200MB)"

if [ -s "$log" ]; then echo "──── server log ────"; sed 's/^/      /' "$log"; fi
rm -f "$log"

echo
if [ "$fails" -eq 0 ]; then
  echo "SMOKE PASSED — safe to install the systemd unit."
else
  echo "SMOKE FAILED ($fails) — fix the FAIL lines above before installing the unit."
fi
exit "$fails"
