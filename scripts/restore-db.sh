#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <backup.sql.gz>"
  exit 1
fi

: "${POSTGRES_DB:=memoryos}"
: "${POSTGRES_USER:=memoryos}"
: "${POSTGRES_PASSWORD:=memoryos}"

gzip -dc "$1" | docker compose exec -T postgres sh -c "PGPASSWORD='${POSTGRES_PASSWORD}' psql -U '${POSTGRES_USER}' '${POSTGRES_DB}'"
echo "Restore complete"
