#!/usr/bin/env bash
# Curio preflight — answers "will this deploy work here, and what has to change?"
#
# Strictly read-only: installs nothing, writes nothing, restarts nothing.
# Safe to run on a Pi already serving other things. Run it before DEPLOY.md.
#
#   bash deploy/preflight.sh
#
# Every line is prefixed OK / WARN / STOP. A STOP means the deploy would fail
# or damage something; a WARN means it works but wants a decision.

say()  { printf '%-5s %s\n' "$1" "$2"; }
have() { command -v "$1" >/dev/null 2>&1; }

echo "──────── host ────────"
say INFO "$(uname -m) · $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"
say INFO "model: $(cat /proc/device-tree/model 2>/dev/null | tr -d '\0' || true)$( [ -r /proc/device-tree/model ] || echo unknown )"
say INFO "user: $(whoami)  home: $HOME"
# The unit and the docs hardcode an account; check this box matches.
unit_user=$(sed -n 's/^User=//p' "$(dirname "$0")/curio.service" 2>/dev/null | head -1)
if [ -n "$unit_user" ] && [ "$(whoami)" != "$unit_user" ]; then
  say WARN "curio.service says User=$unit_user but you are '$(whoami)' — paths need rewriting"
elif [ -n "$unit_user" ]; then
  say OK "curio.service matches this account ($unit_user)"
fi

echo "──────── memory ────────"
free -m | awk '/^Mem:/ {printf "INFO  total %sMB · used %sMB · available %sMB\n", $2, $3, $7}'
avail=$(free -m | awk '/^Mem:/ {print $7}')
# Unit caps Curio at 200M; it should sit near 80M.
if   [ "${avail:-0}" -lt 120 ]; then say STOP "only ${avail}MB free — Curio needs ~80MB and is capped at 200M"
elif [ "${avail:-0}" -lt 250 ]; then say WARN "${avail}MB free — tight; consider swap or trimming a service"
else say OK   "${avail}MB available, comfortable for a ~80MB service"; fi
if swapon --show 2>/dev/null | grep -q .; then
  swapon --show --noheadings 2>/dev/null | awk '{print "INFO  swap: "$1" "$3}'
else
  say WARN "no swap — a memory spike will OOM-kill rather than slow down"
fi

echo "──────── disk ────────"
df -h "$HOME" | awk 'NR==2 {printf "INFO  %s used of %s (%s), %s free\n", $3, $2, $5, $4}'
freek=$(df -k "$HOME" | awk 'NR==2 {print $4}')
[ "${freek:-0}" -lt 1048576 ] && say WARN "under 1GB free — venv + node_modules want ~500MB" || say OK "enough disk"

echo "──────── python ────────"
if have python3; then
  pv=$(python3 -c 'import sys; print("%d.%d"%sys.version_info[:2])')
  say INFO "python3 $pv"
  python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,9) else 1)' \
    && say OK "meets Flask 3.0 requirement (3.9+)" \
    || say STOP "python $pv too old — Flask 3.0.3 needs 3.9+"
  python3 -c 'import venv' 2>/dev/null && say OK "venv module present" \
    || say STOP "venv missing — apt install python3-venv"
  python3 -c 'import ensurepip' 2>/dev/null || say WARN "ensurepip missing — venv creation may fail"
else
  say STOP "no python3"
fi
# argon2-cffi is the one dependency that may compile from source on ARM.
if have dpkg; then
  dpkg -s libffi-dev  >/dev/null 2>&1 && say OK "libffi-dev present (argon2-cffi builds if no wheel)" \
    || say WARN "libffi-dev absent — fine if a wheel exists, else argon2-cffi fails to build"
  dpkg -s build-essential >/dev/null 2>&1 || say WARN "build-essential absent — same caveat"
fi
grep -qi "raspbian\|raspberry" /etc/os-release 2>/dev/null \
  && say OK "Raspberry Pi OS — piwheels usually supplies prebuilt ARM wheels"

echo "──────── node / frontend build ────────"
if have node && have npm; then
  say INFO "node $(node -v) · npm $(npm -v)"
  node -e 'process.exit(parseInt(process.versions.node)>=20?0:1)' \
    && say OK "node 20+, Vite 7 can build here" \
    || say WARN "node too old for Vite 7 — build dist/ elsewhere and copy it over"
  [ "${avail:-0}" -lt 400 ] && say WARN "Vite build is memory-hungry; on this RAM prefer building elsewhere"
else
  say INFO "node absent — not a problem: build dist/ elsewhere and copy it over"
fi

echo "──────── ports ────────"
listening=$( (ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null) | grep LISTEN )
if echo "$listening" | grep -qE '[:.]5000\b'; then
  say STOP "port 5000 is TAKEN — Curio's default; needs changing:"
  echo "$listening" | grep -E '[:.]5000\b' | sed 's/^/      /'
else
  say OK "port 5000 free"
fi
echo "INFO  currently listening:"
echo "$listening" | awk '{print "      "$4}' | sort -u | head -15

echo "──────── existing services ────────"
systemctl list-units --type=service --state=running --no-pager --no-legend 2>/dev/null \
  | awk '{print "      "$1}' | head -25
systemctl list-unit-files 2>/dev/null | grep -q '^curio\.service' \
  && say WARN "curio.service already installed — this would be an upgrade, not a fresh install" \
  || say OK "no existing curio.service"

echo "──────── top memory consumers ────────"
ps -eo rss,comm --sort=-rss 2>/dev/null | awk 'NR>1 && NR<=8 {printf "      %6.1f MB  %s\n", $1/1024, $2}'

echo "──────── shared surfaces (I will not touch these without asking) ────────"
for w in caddy nginx apache2; do have $w && say INFO "web server: $w ($( $w -v 2>&1 | head -1 ))"; done
[ -f /etc/caddy/Caddyfile ] && say INFO "Caddyfile present"
[ -d /etc/nginx/sites-enabled ] && { say INFO "nginx sites:"; ls /etc/nginx/sites-enabled 2>/dev/null | sed 's/^/      /'; }
if have cloudflared; then
  say INFO "cloudflared $(cloudflared --version 2>&1 | head -1)"
  ls /etc/cloudflared/ ~/.cloudflared/ 2>/dev/null | sed 's/^/      /' | head -8
else
  say WARN "cloudflared absent — needed to expose Curio publicly"
fi

echo "──────── permissions ────────"
sudo -n true 2>/dev/null && say OK "passwordless sudo" \
  || say INFO "sudo needs a password — run the systemd steps yourself"

echo "──────── existing curio ────────"
# A bare checkout is expected — you just cloned it. Only a previous *install*
# (a venv, or a live database) means this run is an upgrade rather than a fresh
# deploy, so only that is worth flagging.
for d in "$HOME/curio" /opt/curio /srv/curio; do
  [ -d "$d" ] || continue
  if [ -d "$d/backend/.venv" ] || ls "$d"/backend/*.db >/dev/null 2>&1; then
    say WARN "existing install at $d (venv or database present) — this is an upgrade"
  else
    say OK "checkout at $d, not yet installed"
  fi
done

echo
echo "PREFLIGHT DONE — paste this whole output back."
