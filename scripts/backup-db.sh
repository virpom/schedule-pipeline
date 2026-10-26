#!/usr/bin/env bash
# Бэкап базы расписания (план 011).
#
# cp нельзя: при активной записи копия будет битой. `.backup` в sqlite3
# атомарен и безопасен при работающей базе, в том числе в режиме WAL —
# он копирует и содержимое WAL, поэтому копия получается полной.
set -euo pipefail

DATA=/home/virprom/schedule-pipeline/data
DB="$DATA/database.db"
STAMP=$(date +%Y%m%d-%H%M%S)
OUT="$DATA/database.backup-$STAMP.db"

if [ ! -f "$DB" ]; then
    echo "$(date '+%F %T') базы нет: $DB" >&2
    exit 1
fi

sqlite3 "$DB" ".backup '$OUT'"

# Битый бэкап хуже отсутствующего: на него понадеются.
if ! sqlite3 "$OUT" "PRAGMA integrity_check" | grep -q '^ok$'; then
    echo "$(date '+%F %T') бэкап битый, удаляю: $OUT" >&2
    rm -f "$OUT"
    exit 1
fi

# Оставить 14 последних.
ls -1t "$DATA"/database.backup-*.db 2>/dev/null | tail -n +15 | xargs -r rm -f

SIZE=$(du -h "$OUT" | cut -f1)
ROWS=$(sqlite3 "$OUT" "select count(*) from users")
echo "$(date '+%F %T') ок: $OUT ($SIZE, юзеров: $ROWS)"
