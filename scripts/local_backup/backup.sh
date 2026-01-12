#!/usr/bin/env bash
set -euo pipefail

DATE=$(date +%F)
ROOT="${BACKUPS_PATH:-/var/lib/rediska/backups}"
MYSQL_DUMP_DIR="$ROOT/mysql"
ATTACH_DIR="$ROOT/attachments/$DATE"

mkdir -p "$MYSQL_DUMP_DIR" "$ATTACH_DIR"

echo "Starting backup for $DATE..."

# DB dump
echo "Dumping MySQL database..."
docker exec rediska-mysql sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' \
  | gzip > "$MYSQL_DUMP_DIR/$DATE.sql.gz"

sha256sum "$MYSQL_DUMP_DIR/$DATE.sql.gz" > "$MYSQL_DUMP_DIR/$DATE.sql.gz.sha256"
echo "MySQL dump complete: $MYSQL_DUMP_DIR/$DATE.sql.gz"

# Attachments snapshot (simple; replace with rsync/incremental later)
echo "Snapshotting attachments..."
cp -a "${ATTACHMENTS_PATH:-/var/lib/rediska/attachments}/." "$ATTACH_DIR/" 2>/dev/null || echo "No attachments to backup"
echo "Attachments snapshot complete: $ATTACH_DIR"

echo "Backup complete!"
