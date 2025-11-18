# Testing & Validation

This directory contains comprehensive testing infrastructure for the WOTR platform.

## Test Structure

```
tests/
├── integration/          # Integration tests (end-to-end pipeline)
├── load/                 # Load testing with Locust
├── benchmark/            # Performance benchmarks
└── requirements.txt      # Test dependencies
services/api/tests/       # Unit tests for FastAPI
```

## Setup

Install test dependencies:
```powershell
pip install -r tests/requirements.txt
```

## Unit Tests

Unit tests for FastAPI endpoints (no external dependencies required):

```powershell
# Run all unit tests
pytest services/api/tests/ -v

# Run with coverage
pytest services/api/tests/ --cov=services/api/app --cov-report=html

# Run specific test class
pytest services/api/tests/test_api.py::TestHealthEndpoint -v
```

### Test Coverage

- `/health` endpoint (with and without auth)
- `/metrics` endpoint (Prometheus format)
- `/ingest` endpoint (authentication, validation, error handling)
- `/retention-policies` endpoint
- Authentication module

## Integration Tests

Integration tests require running services:

```powershell
# Start services
docker-compose up -d

# Wait for services to be ready
Start-Sleep -Seconds 30

# Run integration tests
pytest tests/integration/ -v -s

# Mark as integration tests
pytest -m integration -v
```

### Coverage

- Complete data pipeline (API → Kafka → ClickHouse)
- PostgreSQL metadata writes
- ClickHouse consumer processing
- Multiple concurrent ingests
- Metrics updates after operations
- Error handling and validation

## Load Testing

Load testing uses Locust for HTTP load generation.

### Basic Load Test

```powershell
# 10 users, 2 users/sec spawn rate, 1 minute
locust -f tests/load/load_test.py --host http://localhost:8000 -u 10 -r 2 --run-time 1m --headless
```

### Moderate Load

```powershell
# 100 users, 10 users/sec, 5 minutes
locust -f tests/load/load_test.py --host http://localhost:8000 -u 100 -r 10 --run-time 5m --headless
```

### Stress Test

```powershell
# 1000 users, 50 users/sec, 10 minutes
locust -f tests/load/load_test.py --host http://localhost:8000 -u 1000 -r 50 --run-time 10m --headless
```

### Interactive Web UI

```powershell
# Start Locust web interface (access at http://localhost:8089)
locust -f tests/load/load_test.py --host http://localhost:8000
```

### User Types

- **IngestUser**: Balanced mix of ingest (weight 10), health (2), metrics (1)
- **HighVolumeIngestUser**: Rapid-fire ingests with minimal wait time
- **ReadHeavyUser**: Mostly read operations (health/metrics checks)

## Performance Benchmarks

Baseline performance measurements:

```powershell
# Run all benchmarks
python tests/benchmark/benchmark.py
```

Measures:
- `/health` endpoint latency (100 requests)
- `/metrics` endpoint latency (50 requests)
- `/ingest` endpoint latency (50 requests)
- Concurrent ingest throughput (100 requests, 10 workers)
- High concurrency throughput (200 requests, 20 workers)

Statistics reported:
- Mean, median, min, max
- Standard deviation
- P50, P95, P99 percentiles

## Continuous Integration

Tests are integrated into CI pipeline (`.github/workflows/ci.yml`):

```yaml
- name: Run unit tests
  run: pytest services/api/tests/ -v --cov

- name: Run integration tests
  run: pytest tests/integration/ -v -m integration
```

## Test Configuration

`pytest.ini` configures:
- Test discovery paths
- Coverage reporting (terminal, HTML, XML)
- Test markers (unit, integration, load, slow)
- Coverage exclusions

## Common Test Scenarios

### Test Authentication

```python
# Unit test example
def test_requires_auth():
    response = client.post("/ingest", json={"payload": {}})
    assert response.status_code == 401
```

### Test Integration

```python
# Integration test example
def test_end_to_end():
    # Send ingest
    response = requests.post(f"{API_URL}/ingest", json=payload, headers=headers)
    assert response.status_code == 200
    
    # Wait for processing
    time.sleep(10)
    
    # Verify in ClickHouse
    result = clickhouse_client.execute("SELECT * FROM wotr.ingested_data WHERE id = ...", )
    assert len(result) > 0
```

## Troubleshooting

### Tests fail with connection errors

Ensure services are running:
```powershell
docker-compose ps
docker-compose logs fastapi
```

### Integration tests timeout

Increase sleep times in tests or check consumer logs:
```powershell
docker-compose logs consumer
```

### Load tests show high error rate

Check service resources and scale if needed:
```powershell
docker stats
```

## Best Practices

1. **Run unit tests locally** before committing
2. **Run integration tests** after major changes
3. **Perform load testing** before production deployments
4. **Baseline benchmarks** regularly to detect performance regressions
5. **Review coverage reports** to identify untested code

## Metrics to Monitor

During load testing, monitor:
- Response time percentiles (P50, P95, P99)
- Error rate (should be <1%)
- Throughput (requests/sec)
- Resource utilization (CPU, memory)
- Database query latency
- Kafka consumer lag
