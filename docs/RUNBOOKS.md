# WOTR Platform Operational Runbooks

## Overview
This document contains operational procedures, incident response guides, and troubleshooting steps for the WOTR data platform.

## Table of Contents
1. [Common Issues](#common-issues)
2. [Incident Response](#incident-response)
3. [Recovery Procedures](#recovery-procedures)
4. [Monitoring & Alerts](#monitoring--alerts)
5. [Escalation Paths](#escalation-paths)
6. [Maintenance Procedures](#maintenance-procedures)

---

## Common Issues

### Issue: High Ingestion Latency

**Symptoms:**
- `/ingest` endpoint responding slowly (>500ms)
- p95 latency alerts firing
- User complaints about slow API

**Investigation:**
1. Check admin dashboard: http://localhost:8000/admin/
   - Look at "Events Last Hour" and "Events Last 24h" for spikes
   - Check service health for all dependencies

2. Check Grafana dashboards:
   - FastAPI dashboard: http://localhost:3000 → "WOTR FastAPI Dashboard"
   - Look for latency breakdown by component

3. Check service health:
   ```powershell
   curl http://localhost:8000/health
   ```

4. Query ClickHouse for recent events:
   ```sql
   -- Use data explorer: http://localhost:8000/explorer/
   SELECT event_type, count() as cnt, avg(size_bytes) as avg_size
   FROM wotr.ingested_data
   WHERE created_at > now() - INTERVAL 1 HOUR
   GROUP BY event_type
   ORDER BY cnt DESC
   ```

**Common Causes & Solutions:**

| Cause | Detection | Solution |
|-------|-----------|----------|
| MinIO overload | Check MinIO status in admin dashboard | Scale MinIO, add more storage nodes |
| Kafka backlog | Check consumer lag: `docker-compose logs consumer` | Scale consumers, increase partitions |
| PostgreSQL connection exhaustion | Check Postgres status, connection count | Increase connection pool size, restart Postgres |
| ClickHouse slow queries | Check ClickHouse logs: `docker-compose logs clickhouse` | Optimize queries, add indexes, materialize views |

**Resolution Steps:**
1. Identify bottleneck (MinIO/Kafka/Postgres/ClickHouse)
2. Scale the bottleneck service or restart if needed
3. Verify latency returns to normal (<200ms p95)
4. Document incident in post-mortem

---

### Issue: Validation Failures Spike

**Symptoms:**
- Validation failures metric increasing
- 422 errors returned from `/ingest`
- DLQ messages accumulating

**Investigation:**
1. Check admin dashboard for validation failure count
2. Query recent validation failures in data explorer:
   ```sql
   SELECT id, event_type, payload, error_message
   FROM wotr.ingested_data
   WHERE validation_status = 'failed'
   ORDER BY created_at DESC
   LIMIT 50
   ```

3. Check DLQ messages in admin dashboard:
   - Navigate to DLQ section
   - Look for patterns in error messages

4. Review API logs for validation errors:
   ```powershell
   docker-compose logs fastapi | Select-String "Validation failed"
   ```

**Common Causes & Solutions:**

| Cause | Detection | Solution |
|-------|-----------|----------|
| Schema change in upstream | Pattern of same error type | Coordinate schema evolution with upstream team |
| Invalid data from client | Random validation errors | Contact client, provide validation documentation |
| Schema drift | Errors on specific event types | Update Avro schema, redeploy |
| Missing required fields | "required_field" in error messages | Update client to include required fields |

**Resolution Steps:**
1. Identify root cause (schema change, bad client, etc.)
2. If schema issue: update `services/api/app/schemas.py` and `schema_evolution.py`
3. If client issue: contact client with examples from DLQ
4. Retry valid DLQ messages after fix:
   - Use admin dashboard: http://localhost:8000/admin/
   - Click "Retry" on DLQ messages
5. Monitor validation failures return to baseline

---

### Issue: Service Down (503 Errors)

**Symptoms:**
- `/health` endpoint returns 500 or times out
- Service status shows "down" in admin dashboard
- Alerts firing for service availability

**Investigation:**
1. Check which services are down:
   ```powershell
   docker-compose ps
   ```

2. Check admin dashboard service health table
3. Check container logs for crashed service:
   ```powershell
   docker-compose logs --tail=100 <service-name>
   ```

4. Check resource usage:
   ```powershell
   docker stats
   ```

**Common Causes & Solutions:**

| Service | Common Causes | Solution |
|---------|---------------|----------|
| FastAPI | OOM, uncaught exception | Check logs, restart: `docker-compose restart fastapi` |
| Postgres | Connection exhaustion, disk full | Check connections: `SELECT count(*) FROM pg_stat_activity;`, restart if needed |
| ClickHouse | Memory pressure, disk full | Check disk: `df -h`, increase memory limits |
| MinIO | Disk full, network issues | Check disk usage, restart MinIO |
| Kafka/Redpanda | Log segment issues, memory | Check logs, increase heap size if needed |

**Resolution Steps:**
1. Identify crashed service from `docker-compose ps`
2. Check logs: `docker-compose logs <service>`
3. Restart service: `docker-compose restart <service>`
4. If restart fails, check disk space: `df -h`
5. If disk full, clean up old data or add storage
6. Verify service health returns to normal
7. Document incident and add monitoring

---

### Issue: DLQ Messages Accumulating

**Symptoms:**
- DLQ message count increasing in admin dashboard
- Consumer logs show repeated failures
- Data not appearing in ClickHouse

**Investigation:**
1. Check admin dashboard DLQ section
2. Review DLQ messages for patterns:
   ```powershell
   # Use admin dashboard: http://localhost:8000/admin/
   # Or check MinIO directly
   docker exec wotr_dbms_platform-minio-1 mc ls minio/raw-data/dead-letters/
   ```

3. Check consumer logs for errors:
   ```powershell
   docker-compose logs consumer | Select-String "ERROR"
   ```

4. Check ClickHouse connectivity:
   ```powershell
   curl http://localhost:8123/ping
   ```

**Common Causes & Solutions:**

| Cause | Detection | Solution |
|-------|-----------|----------|
| ClickHouse schema mismatch | "column not found" in logs | Update ClickHouse schema in `consumer_with_dlq.py` |
| Network issues | Timeout errors | Check network, restart consumer |
| Invalid data format | JSON parse errors | Fix upstream data format, update validation |
| ClickHouse down | Connection refused | Restart ClickHouse: `docker-compose restart clickhouse` |

**Resolution Steps:**
1. Identify root cause from error messages
2. Fix underlying issue (schema, network, etc.)
3. Retry DLQ messages from admin dashboard
4. Monitor DLQ count decreases
5. If messages still fail, investigate further or delete invalid messages

---

## Incident Response

### Severity Levels

| Severity | Definition | Response Time | Example |
|----------|------------|---------------|---------|
| P0 - Critical | Complete service outage, data loss | 15 minutes | All services down, database corruption |
| P1 - High | Major functionality impaired | 1 hour | One critical service down, high error rate |
| P2 - Medium | Partial functionality impaired | 4 hours | Slow performance, non-critical service down |
| P3 - Low | Minor issue, workaround exists | Next business day | UI glitch, non-critical feature broken |

### Incident Response Process

1. **Detect & Alert**
   - Automated: Prometheus alerts, Grafana dashboards
   - Manual: User reports, monitoring dashboards

2. **Acknowledge**
   - Acknowledge alert in monitoring system
   - Create incident ticket
   - Notify team via Slack/email

3. **Investigate**
   - Check admin dashboard: http://localhost:8000/admin/
   - Review Grafana dashboards
   - Check service logs: `docker-compose logs <service>`
   - Use data explorer for queries: http://localhost:8000/explorer/

4. **Mitigate**
   - Apply immediate fix (restart service, scale resources)
   - Document mitigation steps in incident ticket

5. **Resolve**
   - Verify issue resolved via monitoring
   - Close incident ticket
   - Schedule post-mortem (P0/P1 only)

6. **Post-Mortem**
   - Document timeline, root cause, impact
   - Identify action items to prevent recurrence
   - Update runbooks with learnings

---

## Recovery Procedures

### Full Platform Restart

**When to use:** Complete platform failure, maintenance window, or major configuration change

```powershell
# Stop all services
docker-compose down

# Remove volumes (CAUTION: deletes all data)
docker-compose down --volumes

# Rebuild images
docker-compose build

# Start services
docker-compose up -d

# Wait for services to be healthy
Start-Sleep -Seconds 30

# Check health
curl http://localhost:8000/health

# Verify admin dashboard
Start-Process "http://localhost:8000/admin/"
```

### Service-Specific Recovery

**FastAPI Recovery:**
```powershell
# Restart FastAPI
docker-compose restart fastapi

# Check logs
docker-compose logs -f fastapi

# Verify health
curl http://localhost:8000/health
```

**Postgres Recovery:**
```powershell
# Restart Postgres
docker-compose restart postgres

# Check if accepting connections
docker exec wotr_dbms_platform-postgres-1 pg_isready -U postgres

# If corrupted, restore from backup
# (Backup procedures not yet implemented - TODO)
```

**ClickHouse Recovery:**
```powershell
# Restart ClickHouse
docker-compose restart clickhouse

# Check if responding
curl http://localhost:8123/ping

# Verify data integrity
docker exec wotr_dbms_platform-clickhouse-1 clickhouse-client --query "SELECT count() FROM wotr.ingested_data"
```

**MinIO Recovery:**
```powershell
# Restart MinIO
docker-compose restart minio

# Check buckets
docker exec wotr_dbms_platform-minio-1 mc ls minio/

# Verify bucket exists
docker exec wotr_dbms_platform-minio-1 mc ls minio/raw-data/
```

**Kafka/Redpanda Recovery:**
```powershell
# Restart Redpanda
docker-compose restart redpanda

# Check topics
docker exec wotr_dbms_platform-redpanda-1 rpk topic list

# Check consumer lag
docker exec wotr_dbms_platform-redpanda-1 rpk group describe consumer-group
```

### Data Recovery

**Recover from DLQ:**
1. Navigate to admin dashboard: http://localhost:8000/admin/
2. Review DLQ messages
3. Fix underlying issue (schema, service, etc.)
4. Click "Retry" on each message
5. Verify data appears in ClickHouse via data explorer

**Recover from MinIO (if consumer failed):**
```powershell
# List objects in raw bucket
docker exec wotr_dbms_platform-minio-1 mc ls minio/raw-data/raw/

# Manually republish to Kafka (if needed)
# Use tools/ingest_test.py or custom script
```

---

## Monitoring & Alerts

### Key Metrics to Monitor

1. **API Metrics**
   - Request rate: `rate(fastapi_requests_total[5m])`
   - Error rate: `rate(fastapi_error_total[5m])`
   - Latency p95: `histogram_quantile(0.95, fastapi_request_duration_seconds)`
   - Validation failures: `rate(wotr_validation_failures_total[5m])`

2. **Service Health**
   - Postgres status: `postgres_status`
   - ClickHouse status: `clickhouse_status`
   - MinIO status: `minio_status`
   - Kafka status: `kafka_status`

3. **Data Pipeline**
   - Ingest rate: `rate(wotr_ingest_total[5m])`
   - DLQ message count: `wotr_dlq_messages_total`
   - Consumer lag: Check Redpanda metrics
   - Data quality score: `wotr_data_quality_score`

4. **System Resources**
   - CPU usage: Container CPU %
   - Memory usage: Container memory %
   - Disk usage: Host disk space
   - Network I/O: Container network bytes

### Alert Rules

**Configured in `observability/alerts.yml`:**

1. **HighErrorRate**
   - Threshold: >5 errors per minute
   - Severity: P1
   - Action: Check logs, restart service if needed

2. **HighLatency**
   - Threshold: p95 >1s for 5 minutes
   - Severity: P1
   - Action: Check service health, identify bottleneck

3. **ServiceDown**
   - Threshold: Service status = 0
   - Severity: P0
   - Action: Restart service immediately

4. **HighValidationFailures**
   - Threshold: >10 failures per minute
   - Severity: P2
   - Action: Check DLQ, investigate schema issues

### Dashboard URLs

- **Admin Dashboard:** http://localhost:8000/admin/
- **Data Explorer:** http://localhost:8000/explorer/
- **Grafana:** http://localhost:3000 (admin/admin)
- **Prometheus:** http://localhost:9090
- **Jaeger:** http://localhost:16686
- **MinIO Console:** http://localhost:9000 (minioadmin/minioadmin)

---

## Escalation Paths

### On-Call Rotation
- **Primary:** Platform team on-call engineer
- **Secondary:** Senior platform engineer
- **Escalation:** Engineering manager

### Contact Information
```
Primary On-Call: [Phone/Slack]
Secondary On-Call: [Phone/Slack]
Engineering Manager: [Phone/Slack]
Platform Team Slack: #platform-team
Incident Channel: #incidents
```

### Escalation Criteria

**Escalate to Secondary if:**
- P0 incident not resolved within 30 minutes
- Unfamiliar issue requiring expertise
- Data loss suspected
- Security breach suspected

**Escalate to Manager if:**
- P0 incident not resolved within 1 hour
- Multiple cascading failures
- Customer-facing impact >2 hours
- Legal/compliance implications

---

## Maintenance Procedures

### Scheduled Maintenance Window

**Weekly maintenance: Sunday 2 AM - 4 AM UTC**

**Pre-Maintenance Checklist:**
- [ ] Notify stakeholders 48 hours in advance
- [ ] Backup all data (Postgres, ClickHouse, MinIO)
- [ ] Test changes in staging environment
- [ ] Prepare rollback plan
- [ ] Schedule post-maintenance verification

**Maintenance Steps:**
1. Notify in Slack: "Starting maintenance window"
2. Put platform in maintenance mode (if applicable)
3. Perform maintenance tasks
4. Run smoke tests: `make ingest`, check admin dashboard
5. Verify all services healthy
6. Exit maintenance mode
7. Monitor for 30 minutes
8. Notify completion in Slack

### Database Maintenance

**Postgres Vacuum (Monthly):**
```sql
-- Connect to Postgres
docker exec -it wotr_dbms_platform-postgres-1 psql -U postgres -d wotr

-- Vacuum and analyze
VACUUM ANALYZE ingest_meta;

-- Check table size
SELECT pg_size_pretty(pg_total_relation_size('ingest_meta'));
```

**ClickHouse Optimization (Monthly):**
```sql
-- Use data explorer: http://localhost:8000/explorer/

-- Optimize table
OPTIMIZE TABLE wotr.ingested_data FINAL;

-- Check partition sizes
SELECT partition, sum(rows) as rows, sum(bytes_on_disk) as bytes
FROM system.parts
WHERE table = 'ingested_data' AND database = 'wotr'
GROUP BY partition
ORDER BY partition;

-- Drop old partitions (if retention policy applied)
-- ALTER TABLE wotr.ingested_data DROP PARTITION '202311';
```

### Log Rotation

**Docker logs rotation (configured in docker-compose.yml):**
```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

**Manual log cleanup (if needed):**
```powershell
# Stop services
docker-compose down

# Clean logs
docker system prune -af --volumes

# Restart services
docker-compose up -d
```

### Backup Procedures

**MinIO Data Backup (Daily):**
```powershell
# Backup raw data bucket
docker exec wotr_dbms_platform-minio-1 mc mirror minio/raw-data /backup/minio/raw-data-$(Get-Date -Format "yyyyMMdd")

# Backup curated data bucket
docker exec wotr_dbms_platform-minio-1 mc mirror minio/raw-data /backup/minio/curated-$(Get-Date -Format "yyyyMMdd")
```

**Postgres Backup (Daily):**
```powershell
# Dump Postgres database
docker exec wotr_dbms_platform-postgres-1 pg_dump -U postgres wotr > "backup/postgres-$(Get-Date -Format 'yyyyMMdd').sql"
```

**ClickHouse Backup (Weekly):**
```powershell
# Create backup using clickhouse-backup tool (requires installation)
# docker exec wotr_dbms_platform-clickhouse-1 clickhouse-backup create backup-$(Get-Date -Format "yyyyMMdd")
```

---

## Troubleshooting Tips

### Check Service Connectivity

```powershell
# Check all services are running
docker-compose ps

# Test API
curl http://localhost:8000/health

# Test Postgres
docker exec wotr_dbms_platform-postgres-1 pg_isready -U postgres

# Test ClickHouse
curl http://localhost:8123/ping

# Test MinIO
curl http://localhost:9000/minio/health/live

# Test Kafka
docker exec wotr_dbms_platform-redpanda-1 rpk cluster info
```

### Debug Container Issues

```powershell
# View logs
docker-compose logs -f <service>

# Get shell access
docker exec -it wotr_dbms_platform-<service>-1 /bin/bash

# Check resource usage
docker stats

# Inspect container
docker inspect wotr_dbms_platform-<service>-1
```

### Query Performance Issues

**Slow ClickHouse queries:**
```sql
-- Check slow queries
SELECT
    query_id,
    query,
    elapsed,
    read_rows,
    read_bytes
FROM system.query_log
WHERE type = 'QueryFinish'
ORDER BY elapsed DESC
LIMIT 10;

-- Check table statistics
SELECT
    database,
    table,
    sum(rows) as total_rows,
    sum(bytes_on_disk) as total_bytes
FROM system.parts
WHERE database = 'wotr'
GROUP BY database, table;
```

---

## Quick Reference Commands

```powershell
# Start platform
make up

# Stop platform
make down

# View logs
docker-compose logs -f <service>

# Restart service
docker-compose restart <service>

# Check health
curl http://localhost:8000/health

# Test ingest
make ingest

# Run ETL
make run-etl

# Access admin dashboard
Start-Process "http://localhost:8000/admin/"

# Access data explorer
Start-Process "http://localhost:8000/explorer/"

# Access Grafana
Start-Process "http://localhost:3000"

# Check Prometheus metrics
curl http://localhost:8000/metrics
```

---

## Additional Resources

- **Architecture Documentation:** [README.md](../README.md)
- **Data Pipeline Documentation:** [DATA_PIPELINE.md](DATA_PIPELINE.md)
- **Copilot Instructions:** [.github/copilot-instructions.md](../.github/copilot-instructions.md)
- **Grafana Dashboards:** `observability/`, `fastapi/`, `services/`

---

**Last Updated:** 2025-11-19  
**Maintained By:** Platform Team  
**Review Schedule:** Monthly
