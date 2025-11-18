#!/bin/bash
# Restore script for WOTR platform
# Restores from a backup created by backup.sh

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <backup_directory>"
    echo ""
    echo "Available backups:"
    ls -dt "${BACKUP_ROOT:-/backups}"/*/ 2>/dev/null || echo "  (no backups found)"
    exit 1
fi

BACKUP_DIR="$1"

if [ ! -d "${BACKUP_DIR}" ]; then
    echo "Error: Backup directory not found: ${BACKUP_DIR}"
    exit 1
fi

echo "=== WOTR Restore ==="
echo "Source: ${BACKUP_DIR}"
echo ""
read -p "This will overwrite current data. Continue? (yes/no) " -r
if [[ ! $REPLY =~ ^yes$ ]]; then
    echo "Restore cancelled"
    exit 0
fi

# PostgreSQL restore
if [ -f "${BACKUP_DIR}/postgres_wotr.sql.gz" ]; then
    echo "[PostgreSQL] Starting restore..."
    gunzip -c "${BACKUP_DIR}/postgres_wotr.sql.gz" | docker exec -i postgres psql -U "${POSTGRES_USER:-admin}" "${POSTGRES_DB:-wotr}"
    echo "[PostgreSQL] Restore complete"
else
    echo "[PostgreSQL] Backup file not found, skipping"
fi

# ClickHouse restore
if [ -f "${BACKUP_DIR}/clickhouse_ingested_data.tsv.gz" ]; then
    echo "[ClickHouse] Starting restore..."
    gunzip -c "${BACKUP_DIR}/clickhouse_ingested_data.tsv.gz" | docker exec -i clickhouse clickhouse-client \
        --user "${CLICKHOUSE_USER:-wotr}" --password "${CLICKHOUSE_PASSWORD:-wotrpass}" \
        --query "INSERT INTO wotr.ingested_data FORMAT TabSeparated"
    echo "[ClickHouse] Restore complete"
else
    echo "[ClickHouse] Backup file not found, skipping"
fi

# MinIO restore
if [ -d "${BACKUP_DIR}/minio_raw-data" ]; then
    echo "[MinIO] Starting restore..."
    if command -v mc &> /dev/null; then
        mc alias set wotr-minio "http://${MINIO_ENDPOINT:-localhost:9000}" "${MINIO_ACCESS_KEY:-minioadmin}" "${MINIO_SECRET_KEY:-minioadmin}" || true
        mc mirror "${BACKUP_DIR}/minio_raw-data" wotr-minio/raw-data
        echo "[MinIO] Restore complete"
    else
        echo "[MinIO] Warning: mc (MinIO Client) not installed, skipping MinIO restore"
    fi
else
    echo "[MinIO] Backup directory not found, skipping"
fi

echo ""
echo "=== Restore Complete ==="
