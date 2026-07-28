#!/usr/bin/env bash
# Nightly SQLite backup, keeping the last 14 days.
#
# Uses `sqlite3 .backup` rather than `cp`: the database runs in WAL mode and is
# written to while this runs, so a plain file copy can capture a torn page.
set -euo pipefail

DB="${CURIO_DB:-/home/pi/curio/curio.db}"
DEST="${CURIO_BACKUP_DIR:-/home/pi/curio/backups}"
KEEP_DAYS=14

mkdir -p "$DEST"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$DEST/curio-$STAMP.db"

sqlite3 "$DB" ".backup '$OUT'"
gzip -9 "$OUT"

# Prune old backups.
find "$DEST" -name 'curio-*.db.gz' -mtime "+$KEEP_DAYS" -delete

echo "$(date -Is) backed up to $OUT.gz ($(du -h "$OUT.gz" | cut -f1))"
