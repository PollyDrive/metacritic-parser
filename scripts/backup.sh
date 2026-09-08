#!/usr/bin/env bash
# Дамп БД, с проверкой результата — код успеха у gzip/pg_dump в пайпе врёт,
# если pg_dump упал раньше времени.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"
STAMP="$(date +%Y%m%d_%H%M%S)"
DUMP="$BACKUP_DIR/db_${STAMP}.dump"

mkdir -p "$BACKUP_DIR"

podman exec -i "${DB_CONTAINER:-metacritic-game-tracker_db_1}" \
  pg_dump -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-metacritic_game_tracker_db}" -Fc > "$DUMP"

pg_restore --list "$DUMP" > /dev/null || { echo "ДАМП НЕЧИТАЕМ: $DUMP" >&2; exit 1; }

PREV="$(ls -t "$BACKUP_DIR"/db_*.dump 2>/dev/null | sed -n 2p || true)"
SIZE=$(wc -c < "$DUMP")
if [ -n "$PREV" ]; then
  PREV_SIZE=$(wc -c < "$PREV")
  if [ "$SIZE" -lt $((PREV_SIZE / 2)) ]; then
    echo "ДАМП ПОДОЗРИТЕЛЬНО МАЛ: $SIZE против $PREV_SIZE в предыдущем" >&2
    exit 1
  fi
elif [ "$SIZE" -lt 1024 ]; then
  echo "ДАМП ПУСТ: $SIZE байт" >&2; exit 1
fi

find "$BACKUP_DIR" -name 'db_*.dump' -mtime +"$KEEP_DAYS" -delete

echo "OK: $DUMP ($SIZE байт)"
