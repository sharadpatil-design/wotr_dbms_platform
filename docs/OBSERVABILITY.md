# Observability Enhancements

## Components Added

### 1. Distributed Tracing with OpenTelemetry & Jaeger
- **OpenTelemetry instrumentation** for FastAPI, Kafka, and PostgreSQL
- **Jaeger all-in-one** service for trace collection and visualization
- Automatic trace context propagation across services
- Custom span attributes for event IDs, payload sizes, error tracking

**Access Jaeger UI**: http://localhost:16686

### 2. Structured Logging
- **JSON logging** with consistent format across all services
- Automatic trace context injection (trace_id, span_id)
- Log levels configurable via `LOG_LEVEL` environment variable
- Request lifecycle logging with latency tracking
- Error logging with exception details and stack traces

### 3. Log Aggregation with Grafana Loki
- **Loki** for centralized log storage
- **Promtail** for log collection from Docker containers
- Integrated with Grafana for log visualization
- Automatic label extraction from JSON logs (service, level, container)

**Access Loki**: http://localhost:3100

### 4. Enhanced Consumer Metrics
- **Prometheus metrics** exposed on port 8001:
  - `consumer_messages_consumed_total` - Total messages consumed
  - `consumer_messages_processed_total{status}` - Success/error counts
  - `consumer_processing_duration_seconds` - Processing latency histogram
  - `consumer_clickhouse_insert_duration_seconds` - Insert latency
  - `consumer_errors_total{error_type}` - Errors by type
- Structured logging for all consumer operations
- Enhanced error handling with detailed logging

## Configuration

### Environment Variables

#### FastAPI Service
```bash
TRACING_ENABLED=true          # Enable/disable tracing
JAEGER_HOST=jaeger            # Jaeger agent host
JAEGER_PORT=6831              # Jaeger agent port
LOG_LEVEL=INFO                # DEBUG, INFO, WARNING, ERROR
LOG_FORMAT=json               # json or text
SERVICE_NAME=wotr-api         # Service identifier
ENVIRONMENT=development       # Deployment environment
```

#### Consumer Service
```bash
LOG_LEVEL=INFO                # Logging level
LOG_FORMAT=json               # Log format
METRICS_PORT=8001             # Prometheus metrics port
ENVIRONMENT=development       # Deployment environment
```

## Usage

### Start All Services
```bash
make build
make up
```

### View Distributed Traces
1. Open Jaeger UI: http://localhost:16686
2. Select service: `wotr-api`
3. Click "Find Traces"
4. Explore trace details showing:
   - Request flow through FastAPI → MinIO → Kafka → Postgres
   - Individual span timings
   - Error tracking and exceptions

### View Logs in Grafana
1. Open Grafana: http://localhost:3000 (admin/admin)
2. Go to "Explore"
3. Select "Loki" datasource
4. Query examples:
   ```logql
   {service="wotr-api"} |= "error"
   {container="fastapi"} | json | level="ERROR"
   {service="wotr-consumer"} | json | line_format "{{.message}}"
   ```

### View Consumer Metrics
1. Open Prometheus: http://localhost:9090
2. Query examples:
   ```promql
   rate(consumer_messages_processed_total[5m])
   histogram_quantile(0.95, consumer_processing_duration_seconds_bucket)
   consumer_errors_total
   ```

3. Or view in Grafana dashboards

## Tracing Examples

### Ingest Request Trace
```
wotr-api: ingest_event (parent span)
├── minio_upload (child span)
├── kafka_publish (child span)
└── postgres_insert (child span)
```

### Health Check Trace
```
wotr-api: health_check (parent span)
├── postgres_check
├── minio_check
├── kafka_check
└── clickhouse_check
```

## Structured Log Format

```json
{
  "timestamp": 1700318400.123,
  "level": "INFO",
  "service": "wotr-api",
  "environment": "development",
  "name": "app.main",
  "message": "Request processed",
  "request_id": "abc123",
  "method": "POST",
  "path": "/ingest",
  "status_code": 200,
  "latency": 0.045,
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "00f067aa0ba902b7"
}
```

## Monitoring & Alerts

### Key Metrics to Monitor

1. **Request Latency**
   - `histogram_quantile(0.95, fastapi_request_duration_seconds_bucket)`
   - Alert if p95 > 1s

2. **Error Rate**
   - `rate(fastapi_error_total[5m])`
   - Alert if error rate > 5%

3. **Consumer Lag**
   - `consumer_lag`
   - Alert if lag > 1000

4. **Processing Errors**
   - `rate(consumer_errors_total[5m])`
   - Alert if error rate > 1%

### Create Grafana Dashboard

Import the provided dashboard JSON or create custom panels:

1. **Request Rate**: `rate(fastapi_requests_total[5m])`
2. **Request Latency (p50, p95, p99)**: Histogram queries
3. **Error Rate**: `rate(fastapi_error_total[5m])`
4. **Consumer Throughput**: `rate(consumer_messages_processed_total[1m])`
5. **Consumer Latency**: Processing duration histogram
6. **Service Health**: Gauge metrics (postgres_status, minio_status, etc.)

## Troubleshooting

### Jaeger Not Receiving Traces
1. Check Jaeger is running: `docker ps | grep jaeger`
2. Verify `TRACING_ENABLED=true` in FastAPI environment
3. Check logs: `docker logs fastapi | grep Tracing`
4. Ensure port 6831/udp is accessible

### Loki Not Collecting Logs
1. Check Promtail is running: `docker ps | grep promtail`
2. Verify Docker socket is mounted: `/var/run/docker.sock`
3. Check Promtail logs: `docker logs promtail`
4. Verify log format is JSON (`LOG_FORMAT=json`)

### Consumer Metrics Not Visible
1. Check metrics endpoint: `curl http://localhost:8001/metrics`
2. Verify Prometheus scrape config includes `consumer:8001`
3. Check consumer logs for startup messages
4. Reload Prometheus configuration

## Performance Impact

- **Tracing overhead**: ~2-5% latency increase
- **Structured logging**: Minimal (<1%)
- **Metrics collection**: Minimal (<1%)
- **Log shipping (Promtail)**: Minimal, asynchronous

## Production Recommendations

1. **Sampling**: Enable trace sampling (e.g., 10%) for high-volume APIs
   ```python
   from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
   sampler = TraceIdRatioBased(0.1)  # 10% sampling
   ```

2. **Log retention**: Configure Loki retention policies
   ```yaml
   limits_config:
     retention_period: 744h  # 31 days
   ```

3. **Separate log levels**: Use INFO in production, DEBUG for troubleshooting
4. **Alert on trace errors**: Set up alerts for high error rates in traces
5. **Regular log cleanup**: Monitor Loki disk usage
6. **Secure Jaeger**: Add authentication for production deployments

## References

- [OpenTelemetry Python](https://opentelemetry.io/docs/instrumentation/python/)
- [Jaeger Documentation](https://www.jaegertracing.io/docs/)
- [Grafana Loki](https://grafana.com/docs/loki/latest/)
- [Prometheus Python Client](https://github.com/prometheus/client_python)
