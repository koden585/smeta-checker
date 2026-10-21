#!/usr/bin/env bash
# Backup Postgres + file blobs into ./backups/<stamp>/.
# Usage: ./scripts/backup.sh [output-dir]
# Needs: running compose stack, root .env with POSTGRES_* and AUDIT_API_TOKEN.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-backups/$(date +%Y%m%d-%H%M%S)}"
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT";; esac
mkdir -p "$OUT"
# shellcheck disable=SC1091
set -a; [ -f .env ] && source .env; set +a
USER="${POSTGRES_USER:-smeta}"
DB="${POSTGRES_DB:-smeta}"
echo "-> postgres dump ($USER@$DB)"
docker compose exec -T db pg_dump -U "$USER" -d "$DB" --no-owner --no-privileges -F c -f /tmp/backup.dump
docker compose cp db:/tmp/backup.dump "$OUT/postgres.dump"
docker compose exec -T db rm /tmp/backup.dump
echo "-> blobs + pdf cache"
docker run --rm -v smeta-checker_blobs:/blobs:ro -v "$OUT:/out" alpine \
  tar -czf /out/blobs.tgz -C /blobs .
docker run --rm -v smeta-checker_pdfcache:/cache:ro -v "$OUT:/out" alpine \
  tar -czf /out/pdfcache.tgz -C /cache .
du -sh "$OUT"/*
echo "OK: $OUT"
