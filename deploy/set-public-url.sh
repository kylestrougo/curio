#!/usr/bin/env bash
# Point Curio at its public hostname and re-secure the session cookie.
#
#   bash deploy/set-public-url.sh https://io.tailXXXX.ts.net
#
# make-env.sh writes a local-only config: an http://localhost URL and
# CURIO_COOKIE_SECURE=0, so a first deploy can be looked at before it is
# reachable. Once it is reachable both have to change together — a Secure
# cookie over plain http is never sent, so flipping only one of them produces
# an app that silently cannot log anyone in.

set -euo pipefail

url="${1:-}"
case "$url" in
  https://*) ;;
  "")  echo "usage: bash deploy/set-public-url.sh https://your-host"; exit 1 ;;
  *)   echo "refusing: the URL must be https, got '$url'"
       echo "a Secure session cookie is not sent over http, so logins would fail."
       exit 1 ;;
esac
url="${url%/}"

repo="$(cd "$(dirname "$0")/.." && pwd)"
env_file="$repo/backend/.env"
[ -f "$env_file" ] || { echo "no $env_file — run deploy/make-env.sh first"; exit 1; }

cp -p "$env_file" "$env_file.bak"

set_kv() {
  if grep -qE "^$1=" "$env_file"; then
    # The URL contains slashes, so use a separator that cannot appear in it.
    sed -i "s|^$1=.*|$1=$2|" "$env_file"
  else
    printf '%s=%s\n' "$1" "$2" >> "$env_file"
  fi
}

set_kv CURIO_PUBLIC_URL "$url"
set_kv CURIO_COOKIE_SECURE 1

echo "CURIO_PUBLIC_URL=$url"
echo "CURIO_COOKIE_SECURE=1"
echo "(previous config saved as .env.bak)"
echo
echo "Restart to pick it up:   sudo systemctl restart curio"
