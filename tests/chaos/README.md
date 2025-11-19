# Chaos Engineering Tests

## Overview
Chaos engineering tests validate the WOTR platform's resilience by intentionally introducing failures and observing system behavior.

## Purpose
- Validate fault tolerance and recovery mechanisms
- Identify single points of failure
- Test monitoring and alerting systems
- Build confidence in production resilience
- Document failure modes and recovery procedures

## Test Categories

### 1. Service Failure Tests (`test_service_failures.py`)
- Stop/restart individual services
- Test graceful degradation
- Validate health checks and failover

### 2. Network Chaos Tests (`test_network_chaos.py`)
- Introduce latency, packet loss, network partitions
- Test timeout and retry logic
- Validate circuit breaker patterns

### 3. Resource Exhaustion Tests (`test_resource_exhaustion.py`)
- CPU throttling
- Memory pressure
- Disk space exhaustion
- Connection pool exhaustion

### 4. Data Corruption Tests (`test_data_corruption.py`)
- Invalid message formats
- Schema mismatches
- Encoding errors

## Prerequisites

```powershell
# Install Python dependencies
pip install pytest docker requests

# Ensure platform is running
docker-compose up -d

# Verify health before tests
curl http://localhost:8000/health
```

## Running Tests

```powershell
# Run all chaos tests
pytest tests/chaos/ -v

# Run specific test category
pytest tests/chaos/test_service_failures.py -v

# Run with detailed output
pytest tests/chaos/ -v -s

# Run specific test
pytest tests/chaos/test_service_failures.py::test_fastapi_restart -v
```

## Safety Guidelines

⚠️ **IMPORTANT:** These tests are **destructive** and should **NEVER** be run in production.

- ✅ Run in local development environment only
- ✅ Ensure no production data in test environment
- ✅ Have rollback plan ready
- ✅ Monitor system during tests
- ❌ Never run in production
- ❌ Never run without team notification
- ❌ Never run during business hours (if shared dev environment)

## Test Execution Pattern

Each test follows this pattern:
1. **Baseline:** Verify system healthy before test
2. **Chaos:** Introduce failure condition
3. **Observe:** Monitor system behavior and metrics
4. **Validate:** Assert expected resilience behavior
5. **Recover:** Restore system to healthy state
6. **Verify:** Confirm full recovery

## Metrics to Monitor

During chaos tests, monitor:
- API response times and error rates
- Service health status
- Queue depths (Kafka consumer lag)
- Database connection pools
- Resource utilization (CPU, memory, disk)
- Alert firing (should trigger)
- Recovery time (time to return to baseline)

## Expected Outcomes

### Passing Test Criteria
- System detects failure quickly (<30s)
- Appropriate alerts fire
- System continues serving requests (degraded or full)
- Automatic recovery when service restored
- No data loss
- Health checks reflect actual state

### Acceptable Degraded Behavior
- Increased latency during failure
- Temporary 503 errors for affected endpoints
- Queue backlog (with eventual catch-up)
- Graceful error messages to clients

### Unacceptable Behavior
- Silent failures (no alerts)
- Data loss or corruption
- Cascading failures
- System does not recover automatically
- Health checks report healthy when service degraded

## Test Results Documentation

After running tests, document:
- Test execution date/time
- Pass/fail status
- Observed behavior
- Alert triggering (expected vs. actual)
- Recovery time
- Any unexpected behavior
- Action items for improvements

## Integration with CI/CD

Chaos tests can be integrated into CI/CD pipeline:
```yaml
# Example GitHub Actions workflow (not included yet)
- name: Run Chaos Tests
  run: |
    docker-compose up -d
    sleep 30  # Wait for services to be healthy
    pytest tests/chaos/ -v --junitxml=chaos-report.xml
    docker-compose down
```

## Additional Resources

- [Principles of Chaos Engineering](https://principlesofchaos.org/)
- [Netflix Chaos Monkey](https://netflix.github.io/chaosmonkey/)
- [WOTR Operational Runbooks](../../docs/RUNBOOKS.md)
- [Admin Dashboard](http://localhost:8000/admin/)
- [Data Explorer](http://localhost:8000/explorer/)
