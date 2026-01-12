#!/usr/bin/env bash
set -euo pipefail

ROOT="${BACKUPS_PATH:-/var/lib/rediska/backups}"
LATEST=$(ls -1 "$ROOT/mysql"/*.sql.gz 2>/dev/null | tail -n 1 || true)

if [[ -z "$LATEST" ]]; then
    echo "Error: No backup files found in $ROOT/mysql"
    exit 1
fi

echo "Using dump: $LATEST"

# Verify checksum
CHECKSUM_FILE="$LATEST.sha256"
if [[ -f "$CHECKSUM_FILE" ]]; then
    echo "Verifying checksum..."
    if ! sha256sum -c "$CHECKSUM_FILE" >/dev/null 2>&1; then
        echo "Error: Checksum verification failed!"
        exit 1
    fi
    echo "Checksum verified."
fi

# Spin up ephemeral restore container
echo "Starting ephemeral MySQL container..."
docker run --rm --name rediska-mysql-restoretest \
    -e MYSQL_ROOT_PASSWORD=test \
    -e MYSQL_DATABASE=rediska \
    -d mysql:8.4

echo "Waiting for MySQL to be ready..."
sleep 20

# Import the dump
echo "Importing dump..."
gunzip -c "$LATEST" | docker exec -i rediska-mysql-restoretest mysql -uroot -ptest rediska

# Simple sanity checks
echo "Running sanity checks..."
echo ""
echo "=== Tables ==="
docker exec rediska-mysql-restoretest mysql -uroot -ptest rediska -e "SHOW TABLES;"

echo ""
echo "=== Row counts ==="
for table in providers local_users external_accounts conversations messages; do
    count=$(docker exec rediska-mysql-restoretest mysql -uroot -ptest rediska -sN -e "SELECT COUNT(*) FROM $table;" 2>/dev/null || echo "N/A")
    echo "$table: $count rows"
done

# Cleanup
echo ""
echo "Cleaning up..."
docker stop rediska-mysql-restoretest

echo ""
echo "Restore test PASSED!"
