#!/bin/sh
set -eu

: "${MYSQL_HOST:?MYSQL_HOST is required}"
: "${MYSQL_PORT:=3306}"
: "${MYSQL_DATABASE:?MYSQL_DATABASE is required}"
: "${MYSQL_USER:?MYSQL_USER is required}"
: "${MYSQL_PASSWORD:?MYSQL_PASSWORD is required}"
: "${BACKUP_ROOT:=/var/backups/commerce-studio}"
: "${MEDIA_SOURCE:=/var/lib/docker/volumes/commerce-studio-media/_data}"
: "${BACKUP_RETENTION_DAYS:=14}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="${BACKUP_ROOT}/${timestamp}"
mkdir -p "$target"

mysqldump \
  --single-transaction \
  --quick \
  --routines \
  --triggers \
  --host="$MYSQL_HOST" \
  --port="$MYSQL_PORT" \
  --user="$MYSQL_USER" \
  --password="$MYSQL_PASSWORD" \
  "$MYSQL_DATABASE" | gzip -9 > "${target}/database.sql.gz"

if [ -d "$MEDIA_SOURCE" ]; then
    tar -czf "${target}/media.tar.gz" -C "$MEDIA_SOURCE" .
fi

find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d \
  -mtime "+${BACKUP_RETENTION_DAYS}" -exec rm -rf -- {} \;

echo "backup completed: ${target}"
