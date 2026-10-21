#!/usr/bin/env bash
# Restore Postgres + file blobs from a backup dir made by backup.sh.
# Usage: ./scripts/restore.sh <backup-dir>
# Destroys current compose data. Needs: compose.yaml + filled root .env.
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="${1:?usage: ./scripts/restore.sh <backup-dir>}"
case "$SRC" in /*) ;; *) SRC="$PWD/$SRC";; esac
[ -f "$SRC/postgres.dump" ] || { echo "no $SRC/postgres.dump"; exit 1; }
# shellcheck disable=SC1091
set -a; [ -f .env ] && source .env; set +a
USER="${POSTGRES_USER:-smeta}"
DB="${POSTGRES_DB:-smeta}"
echo "-> stopping stack, wiping volumes"
docker compose down -q
docker volume rm -f smeta-checker_pgdata smeta-checker_blobs smeta-checker_pdfcache smeta-checker_redisdata >/dev/null 2>&1 || true
docker volume create smeta-checker_pgdata >/dev/null
docker volume create smeta-checker_blobs >/dev/null
docker volume create smeta-checker_pdfcache >/dev/null
echo "-> starting db"
docker compose up -d db
sleep 8
echo "-> restoring postgres"
docker compose cp "$SRC/postgres.dump" db:/tmp/backup.dump
docker compose exec -T db pg_restore -U "$USER" -d "$DB" --no-owner --no-privileges /tmp/backup.dump || true
docker compose exec -T db rm /tmp/backup.dump
echo "-> restoring blobs + pdf cache"
docker run --rm -v smeta-checker_blobs:/blobs -v "$SRC:/in:ro" alpine \
  sh -c 'tar -xzf /in/blobs.tgz -C /blobs'
if [ -f "$SRC/pdfcache.tgz" ]; then
  docker run --rm -v smeta-checker_pdfcache:/cache -v "$SRC:/in:ro" alpine \
    sh -c 'tar -xzf /in/pdfcache.tgz -C /cache'
fi
echo "-> starting full stack"
docker compose up -d --build
docker compose ps --format '{{.Name}} {{.Status}}'
echo "OK: data restored, stack starting"
