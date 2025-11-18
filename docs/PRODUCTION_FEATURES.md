# Production Features - November 18, 2025

## Overview
Added production-ready features including API authentication, data retention policies, and automated backup/restore capabilities.

## 1. API Authentication

### Implementation
- **Authentication Method**: API Key-based authentication via HTTP header
- **Header Name**: `X-API-Key`
- **Module**: `services/api/app/auth.py`

### Features
- Configurable API keys via `API_KEYS` environment variable (comma-separated)
- Default development key: `dev-key-12345` (used if no keys configured)
- Protected endpoints: `/ingest`, `/retention-policies`
- Public endpoints: `/health`, `/metrics` (monitoring)

### Usage Examples

```bash
# Ingest with API key
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-key-12345" \
  -d '{"payload":{"test":"data"}}'

# Without API key (fails with 401)
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"payload":{"test":"data"}}'

# Check retention policies (requires auth)
curl http://localhost:8000/retention-policies \
  -H "X-API-Key: dev-key-12345"
```

### Configuration
In `docker-compose.yml`:
```yaml
environment:
  API_KEYS: "dev-key-12345,prod-key-67890"
```

⚠️ **Production**: Use strong, randomly generated keys and rotate regularly.

## 2. Data Retention Policies

### Implementation
- **Policy Module**: `services/api/app/retention.py`
- **Cleanup Script**: `services/api/retention_cleanup.py`
- **Automation**: `docker-compose.retention.yml`

### Retention Periods (Configurable)

| Component | Default Retention | Environment Variable |
|-----------|------------------|---------------------|
| ClickHouse | 90 days | `CLICKHOUSE_RETENTION_DAYS` |
| MinIO Raw | 30 days | `MINIO_RAW_RETENTION_DAYS` |
| MinIO Curated | 365 days | `MINIO_CURATED_RETENTION_DAYS` |
| PostgreSQL Metadata | 180 days | `POSTGRES_METADATA_RETENTION_DAYS` |

### How It Works

#### ClickHouse
- Uses ClickHouse TTL (Time To Live) feature
- Automatically expires data based on `created_at` timestamp
- Manual cleanup available via `ALTER TABLE ... DELETE`

#### MinIO
- Scans objects in bucket with prefix
- Deletes objects older than retention period based on `last_modified`
- Supports multiple buckets/prefixes

#### PostgreSQL
- Deletes metadata records older than retention period
- Uses `created_at` timestamp for filtering

### Manual Execution

```bash
# Run retention cleanup manually
docker exec fastapi python /app/retention_cleanup.py
```

### Automated Execution

Start the retention scheduler:
```bash
docker-compose -f docker-compose.retention.yml up -d
```

Runs daily at 3 AM by default. Configure schedule:
```bash
RETENTION_SCHEDULE="0 1 * * *" docker-compose -f docker-compose.retention.yml up -d
```

### Monitoring

Check retention policy configuration via API:
```bash
curl http://localhost:8000/retention-policies \
  -H "X-API-Key: dev-key-12345"
```

## 3. Backup and Restore

### Implementation
- **Backup Script**: `scripts/backup.sh`
- **Restore Script**: `scripts/restore.sh`
- **Automation**: `docker-compose.backup.yml`

### Backup Components

1. **PostgreSQL**: Full database dump (pg_dump)
2. **ClickHouse**: TabSeparated export of `wotr.ingested_data`
3. **MinIO**: Mirror of `raw-data` bucket

### Manual Backup

```bash
# Run backup manually
export BACKUP_ROOT=/backups
export POSTGRES_USER=admin
export POSTGRES_PASSWORD=admin
export POSTGRES_DB=wotr
export CLICKHOUSE_USER=wotr
export CLICKHOUSE_PASSWORD=wotrpass
export MINIO_ENDPOINT=localhost:9000
export MINIO_ACCESS_KEY=minioadmin
export MINIO_SECRET_KEY=minioadmin

./scripts/backup.sh
```

### Manual Restore

```bash
# List available backups
ls -lt /backups/

# Restore from specific backup
./scripts/restore.sh /backups/20251118_020000
```

### Automated Backups

Start the backup scheduler:
```bash
docker-compose -f docker-compose.backup.yml up -d
```

Runs daily at 2 AM by default. Configure schedule:
```bash
BACKUP_SCHEDULE="0 4 * * *" docker-compose -f docker-compose.backup.yml up -d
```

### Backup Retention

- Keeps last 7 backups by default
- Configurable via `BACKUP_RETENTION_COUNT` environment variable
- Older backups automatically deleted

### Backup Location

- Default: `/backups` in container
- Mount to host for persistence:
```yaml
volumes:
  - ./backups:/backups
```

## Configuration Summary

### Environment Variables (docker-compose.yml)

```yaml
# API Authentication
API_KEYS: "dev-key-12345,prod-key-67890"

# Retention Policies
CLICKHOUSE_RETENTION_ENABLED: "true"
CLICKHOUSE_RETENTION_DAYS: "90"
MINIO_RAW_RETENTION_ENABLED: "true"
MINIO_RAW_RETENTION_DAYS: "30"
MINIO_CURATED_RETENTION_ENABLED: "false"
MINIO_CURATED_RETENTION_DAYS: "365"
POSTGRES_METADATA_RETENTION_ENABLED: "true"
POSTGRES_METADATA_RETENTION_DAYS: "180"

# Backup Configuration
BACKUP_SCHEDULE: "0 2 * * *"  # 2 AM daily
BACKUP_RETENTION_COUNT: "7"

# Retention Cleanup Schedule
RETENTION_SCHEDULE: "0 3 * * *"  # 3 AM daily
```

## Testing

### Test Authentication

```powershell
# Should succeed
curl -X POST http://localhost:8000/ingest -H "Content-Type: application/json" -H "X-API-Key: dev-key-12345" -d '{"payload":{"test":"auth"}}'

# Should fail (401)
curl -X POST http://localhost:8000/ingest -H "Content-Type: application/json" -d '{"payload":{"test":"auth"}}'
```

### Test Retention Policies

```powershell
# Check policy configuration
curl http://localhost:8000/retention-policies -H "X-API-Key: dev-key-12345"

# Run manual cleanup
docker exec fastapi python /app/retention_cleanup.py
```

### Test Backup/Restore

```powershell
# Create test data
curl -X POST http://localhost:8000/ingest -H "Content-Type: application/json" -H "X-API-Key: dev-key-12345" -d '{"payload":{"test":"backup"}}'

# Run backup (requires scripts to be executable)
docker exec wotr-backup-scheduler /scripts/backup.sh

# Verify backup exists
docker exec wotr-backup-scheduler ls -l /backups/
```

## Security Considerations

### Production Checklist

- [ ] Generate strong, random API keys
- [ ] Store API keys in secrets manager (not environment variables)
- [ ] Use HTTPS for all API traffic
- [ ] Implement rate limiting on `/ingest` endpoint
- [ ] Encrypt backups at rest and in transit
- [ ] Store backups in off-site location (S3, Azure Blob, etc.)
- [ ] Test restore procedure regularly
- [ ] Monitor retention cleanup jobs
- [ ] Audit API key usage
- [ ] Rotate API keys periodically

### Backup Security

- Encrypt backup files before storing
- Use restricted permissions on backup directory
- Implement backup verification/integrity checks
- Store backups in multiple locations
- Test disaster recovery procedures

## Next Steps

1. **Implement Role-Based Access Control (RBAC)**
   - Multiple API keys with different permissions
   - Read-only vs. write access
   - Admin endpoints for key management

2. **Enhanced Monitoring**
   - Track authentication failures
   - Monitor retention cleanup metrics
   - Alert on backup failures

3. **Cloud Integration**
   - Store backups in S3/Azure/GCS
   - Use cloud-native secrets management
   - Implement cross-region replication

4. **Advanced Retention**
   - Tiered retention (hot/warm/cold)
   - Selective retention by data type
   - Data archival to cheaper storage
