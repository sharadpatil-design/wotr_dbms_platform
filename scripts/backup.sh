#!/bin/bash
# Backup script for WOTR platform
# Creates backups of PostgreSQL, ClickHouse, and MinIO data

set -e

BACKUP_DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="${BACKUP_ROOT:-/backups}/${BACKUP_DATE}"
mkdir -p "${BACKUP_DIR}"

echo "=== WOTR Backup - ${BACKUP_DATE} ==="
echo "Backup directory: ${BACKUP_DIR}"

# PostgreSQL backup
echo "[PostgreSQL] Starting backup..."
docker exec postgres pg_dump -U "${POSTGRES_USER:-admin}" "${POSTGRES_DB:-wotr}" > "${BACKUP_DIR}/postgres_wotr.sql"
gzip "${BACKUP_DIR}/postgres_wotr.sql"
echo "[PostgreSQL] Backup complete: ${BACKUP_DIR}/postgres_wotr.sql.gz"

# ClickHouse backup
echo "[ClickHouse] Starting backup..."
docker exec clickhouse clickhouse-client --user "${CLICKHOUSE_USER:-wotr}" --password "${CLICKHOUSE_PASSWORD:-wotrpass}" \
    --query "SELECT * FROM wotr.ingested_data FORMAT TabSeparated" > "${BACKUP_DIR}/clickhouse_ingested_data.tsv"
gzip "${BACKUP_DIR}/clickhouse_ingested_data.tsv"
echo "[ClickHouse] Backup complete: ${BACKUP_DIR}/clickhouse_ingested_data.tsv.gz"

# MinIO backup (using mc client)
echo "[MinIO] Starting backup..."
if command -v mc &> /dev/null; then
    # Configure mc alias if not exists
    mc alias set wotr-minio "http://${MINIO_ENDPOINT:-localhost:9000}" "${MINIO_ACCESS_KEY:-minioadmin}" "${MINIO_SECRET_KEY:-minioadmin}" || true
    
    # Mirror raw-data bucket
    mc mirror wotr-minio/raw-data "${BACKUP_DIR}/minio_raw-data"
    echo "[MinIO] Backup complete: ${BACKUP_DIR}/minio_raw-data"
else
    echo "[MinIO] Warning: mc (MinIO Client) not installed, skipping MinIO backup"
fi

# Create backup manifest
cat > "${BACKUP_DIR}/manifest.json" <<EOF
{
  "backup_date": "${BACKUP_DATE}",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "components": {
    "postgres": "postgres_wotr.sql.gz",
    "clickhouse": "clickhouse_ingested_data.tsv.gz",
    "minio": "minio_raw-data/"
  },
  "environment": {
    "postgres_db": "${POSTGRES_DB:-wotr}",
    "clickhouse_db": "wotr",
    "minio_bucket": "raw-data"
  }
}
EOF

# Calculate backup size
BACKUP_SIZE=$(du -sh "${BACKUP_DIR}" | cut -f1)
echo ""
echo "=== Backup Complete ==="
echo "Size: ${BACKUP_SIZE}"
echo "Location: ${BACKUP_DIR}"

# Retention: Keep last N backups (configurable)
RETENTION_COUNT="${BACKUP_RETENTION_COUNT:-7}"
echo ""
echo "Cleaning up old backups (keeping last ${RETENTION_COUNT})..."
cd "${BACKUP_ROOT:-/backups}"
ls -dt */ | tail -n +$((RETENTION_COUNT + 1)) | xargs -r rm -rf
echo "Cleanup complete"
