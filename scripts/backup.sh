#!/bin/sh
# Резервная копия базы: сразу при запуске и каждый день в BACKUP_TIME (по Ташкенту).
# Копии: ./backups/jac_parts_ГГГГ-ММ-ДД_ЧЧММ.sql.gz, старше BACKUP_KEEP_DAYS дней удаляются.
set -eu
AT="${BACKUP_TIME:-03:00}"
KEEP="${BACKUP_KEEP_DAYS:-14}"
export PGPASSWORD="$POSTGRES_PASSWORD"

backup() {
  file="/backups/jac_parts_$(date +%Y-%m-%d_%H%M).sql.gz"
  if pg_dump -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner | gzip > "$file.tmp"; then
    mv "$file.tmp" "$file"
    echo "$(date '+%F %T') backup OK: $file ($(du -h "$file" | cut -f1))"
  else
    rm -f "$file.tmp"
    echo "$(date '+%F %T') backup FAILED" >&2
  fi
  find /backups -name 'jac_parts_*.sql.gz' -mtime +"$KEEP" -delete
}

backup
last_day="$(date +%F)"
while true; do
  sleep 30
  if [ "$(date +%H:%M)" = "$AT" ] && [ "$(date +%F)" != "$last_day" ]; then
    backup
    last_day="$(date +%F)"
  fi
done
