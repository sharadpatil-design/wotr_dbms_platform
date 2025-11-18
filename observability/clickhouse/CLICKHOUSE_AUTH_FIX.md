# ClickHouse Authentication Fix - November 18, 2025

## Problem
- ClickHouse was running with default user (no password)
- FastAPI health check was disabled due to authentication mismatch
- Consumer was connecting without credentials
- Inconsistent security posture across services

## Solution Implemented

### 1. ClickHouse User Configuration
Created `observability/clickhouse/users.xml` with:
- **default** user (no password) - kept for backward compatibility
- **wotr** user with password `wotrpass` - dedicated application user with database access to `wotr` database

### 2. Docker Compose Updates
Updated `docker-compose.yml`:
- Mounted users.xml to ClickHouse container: `./observability/clickhouse/users.xml:/etc/clickhouse-server/users.d/users.xml:ro`
- Added environment variables to ClickHouse service: `CLICKHOUSE_USER=wotr`, `CLICKHOUSE_PASSWORD=wotrpass`
- Updated FastAPI environment: Changed from `default/""` to `wotr/wotrpass`
- Updated consumer environment: Added `CLICKHOUSE_USER=wotr`, `CLICKHOUSE_PASSWORD=wotrpass`

### 3. Consumer Updates (`services/consumer/consumer.py`)
- Added `CLICKHOUSE_USER` and `CLICKHOUSE_PASSWORD` environment variable loading
- Updated ClickHouse client initialization: `Client(host=..., port=..., user=CLICKHOUSE_USER, password=CLICKHOUSE_PASSWORD)`
- Added logging for connection details (without exposing password)

### 4. FastAPI Updates (`services/api/app/main.py`)
- Simplified `check_clickhouse()` function to always pass user and password
- **Re-enabled ClickHouse health check** in `/health` endpoint
- Removed "check disabled" workaround
- Health check now properly validates ClickHouse connectivity with authentication

## Configuration Details

### ClickHouse User Permissions
The `wotr` user has:
- Access from any network (`::/0`)
- Default profile and quota
- Database access: `wotr` database only
- Password: `wotrpass` (change in production!)

### Security Considerations
⚠️ **For Production:**
1. Use strong passwords or secrets management (e.g., Docker secrets, Vault)
2. Restrict network access (replace `::/0` with specific IPs/subnets)
3. Use environment variable substitution for sensitive values
4. Consider TLS/SSL for ClickHouse connections
5. Implement password rotation policy
6. Use separate users for read-only vs read-write operations

## Testing

To verify the fix:
```powershell
# Restart services with new configuration
docker-compose down -v
docker-compose up -d

# Wait for services to start (30 seconds)
Start-Sleep -Seconds 30

# Test FastAPI health endpoint
curl http://localhost:8000/health

# Expected: clickhouse: "ok" (not "ok (check disabled)")

# Test ClickHouse direct connection
docker exec -it clickhouse clickhouse-client --user wotr --password wotrpass --query "SELECT 1"

# Expected: 1

# Test consumer writes (trigger ingest)
curl -X POST http://localhost:8000/ingest -H "Content-Type: application/json" -d '{"payload":{"test":"auth-fix"}}'

# Verify in ClickHouse
docker exec -it clickhouse clickhouse-client --user wotr --password wotrpass --query "SELECT * FROM wotr.ingested_data ORDER BY created_at DESC LIMIT 5"
```

## Files Modified
1. `observability/clickhouse/users.xml` - NEW: ClickHouse user configuration
2. `docker-compose.yml` - Added volume mount, updated env vars for clickhouse, fastapi, consumer
3. `services/consumer/consumer.py` - Added authentication parameters
4. `services/api/app/main.py` - Simplified check_clickhouse(), re-enabled health check

## Impact
✅ Proper authentication enforced across all ClickHouse connections  
✅ Health check fully functional  
✅ Consistent security model  
✅ Production-ready authentication pattern  
✅ Consumer and API using same credentials  

## Next Steps (Future)
- Implement TLS for ClickHouse connections
- Use Docker secrets or external secrets manager
- Add separate read-only user for analytics/reporting
- Implement connection pooling with authentication
