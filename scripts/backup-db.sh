#!/usr/bin/env sh
set -eu

: "${POSTGRES_DB:=memoryos}"
: "${POSTGRES_USER:=memoryos}"
: "${POSTGRES_PASSWORD:=memoryos}"

mkdir -p backups
timestamp="$(date +%Y%m%d-%H%M%S)"
outfile="backups/${POSTGRES_DB}-${timestamp}.sql.gz"

docker compose exec -T postgres sh -c "PGPASSWORD='${POSTGRES_PASSWORD}' pg_dump -U '${POSTGRES_USER}' '${POSTGRES_DB}'" | gzip > "${outfile}"
echo "Created ${outfile}"
