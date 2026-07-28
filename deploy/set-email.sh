#!/usr/bin/env bash
# Put Gmail credentials into backend/.env and turn live sending on.
#
#   bash deploy/set-email.sh
#
# The app password is read without echo and never appears on the command line,
# so it stays out of shell history and out of the process list. .env is mode
# 600 already; this keeps it that way.

set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
env_file="$repo/backend/.env"
[ -f "$env_file" ] || { echo "no $env_file — run deploy/make-env.sh first"; exit 1; }

read -rp "Gmail address (the sender): " sender
[ -n "$sender" ] || { echo "sender is required"; exit 1; }

# Gmail app passwords are 16 characters, shown in groups of four. People paste
# them with the spaces in, and Gmail accepts either — strip them so the value
# in .env is the canonical form.
read -rsp "App password (16 chars, not your Gmail password): " password; echo
password="${password// /}"
[ -n "$password" ] || { echo "password is required"; exit 1; }
if [ "${#password}" -ne 16 ]; then
  echo "warning: got ${#password} characters, expected 16."
  echo "         An app password comes from myaccount.google.com/apppasswords,"
  echo "         not your normal Gmail password."
  read -rp "Use it anyway? [y/N] " yn
  [ "$yn" = "y" ] || [ "$yn" = "Y" ] || exit 1
fi

read -rp "Port [465 implicit TLS / 587 STARTTLS] (465): " port
port="${port:-465}"

cp -p "$env_file" "$env_file.bak"

set_kv() {
  if grep -qE "^$1=" "$env_file"; then
    python3 - "$env_file" "$1" "$2" <<'PY'
import sys
path, key, val = sys.argv[1], sys.argv[2], sys.argv[3]
lines = open(path).read().splitlines(keepends=True)
# Rewrite in Python rather than sed: an app password can contain characters
# that sed would treat as part of the replacement expression.
with open(path, "w") as f:
    for line in lines:
        f.write(f"{key}={val}\n" if line.startswith(key + "=") else line)
PY
  else
    printf '%s=%s\n' "$1" "$2" >> "$env_file"
  fi
}

set_kv CURIO_SMTP_HOST smtp.gmail.com
set_kv CURIO_SMTP_PORT "$port"
set_kv CURIO_SMTP_USER "$sender"
set_kv CURIO_SMTP_PASSWORD "$password"
set_kv CURIO_MAIL_FROM "$sender"
set_kv CURIO_MAIL_DRY_RUN 0
chmod 600 "$env_file"

echo
echo "sender : $sender"
echo "port   : $port"
echo "dry run: off — mail will actually be sent"
echo "(previous config saved as .env.bak)"
echo
echo "Next:"
echo "  sudo systemctl restart curio"
echo "  cd $repo/backend && .venv/bin/flask send-due-emails --user-id 1"
