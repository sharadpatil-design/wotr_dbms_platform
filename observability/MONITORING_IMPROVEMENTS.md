# Monitoring Improvements - November 18, 2025

## New Dashboards Created

### 1. FastAPI Detailed Dashboard (`observability/dashboards/fastapi_detailed.json`)
Comprehensive FastAPI monitoring with:
- **Request Overview**: Total requests, request rate, error rate, avg/P95 latency, ingest operations
- **Request Trends**: Request rate over time, latency percentiles (P50/P90/P95/P99)
- **Database & Backend Services**: DB query latency, service status summary
- **Detailed Metrics**: Recent errors table, application uptime

### 2. Kafka & Consumer Dashboard (`observability/dashboards/kafka_consumer.json`)
Consumer pipeline monitoring with:
- **Kafka Status**: Broker and ClickHouse status panels
- **Data Pipeline Metrics**: Messages consumed (estimated from ingest), notes on future instrumentation
- **Placeholder panels**: Consumer lag, ClickHouse insert rate (requires consumer instrumentation)

### 3. System Overview Dashboard (`observability/dashboards/system_overview.json`)
High-level platform health with:
- **Platform Health**: Overall system health gauge (5 services), service status grid, FastAPI uptime
- **Request Metrics**: Request rate & errors, P95 latency
- **Data Pipeline**: Total ingests, ingest rate over time
- **Alerts**: Links to Alertmanager and list of configured alerts
- **Navigation**: Links to FastAPI Detailed and Kafka & Consumer dashboards

## Enhanced Prometheus Alerts

Added to `observability/alerts.yml`:

### Advanced FastAPI Alerts
- `FastAPIHighErrorRate`: Error rate > 5% for 3 minutes (critical)
- `FastAPIRequestSpike`: Request rate > 100 req/sec for 2 minutes (warning)
- `FastAPINoTraffic`: No requests for 5 minutes (warning)
- `FastAPISlowDBQueries`: Avg DB query latency > 0.5s for 3 minutes (warning)

### Data Pipeline Alerts
- `IngestRateDrop`: Ingest rate drops below 0.1 ops/sec after being active (warning)
- `MultipleServicesDown`: At least 2 backend services unreachable (critical)

## Dashboard Provisioning Updates

Updated `observability/grafana_provisioning/provisioning/dashboards/dashboards.yml`:
- Added second provider "WOTR Dashboards" pointing to `/etc/grafana/provisioning/dashboards`
- Dashboard folder: "WOTR Platform"
- Auto-refresh every 10 seconds

Updated `docker-compose.yml`:
- Added volume mount for new dashboards directory: `./observability/dashboards:/etc/grafana/provisioning/dashboards:ro`

## Usage

1. Start services: `make up`
2. Access Grafana: http://localhost:3000 (admin/admin)
3. Navigate to "WOTR Platform" folder for new dashboards
4. System Overview dashboard includes navigation links to detailed dashboards

## Future Improvements

### Consumer Instrumentation Needed
To populate Kafka & Consumer dashboard fully, add metrics to `services/consumer/consumer.py`:
- `kafka_consumer_lag` (gauge) - consumer lag in messages
- `kafka_messages_consumed_total` (counter) - total messages consumed
- `clickhouse_inserts_total` (counter) - successful ClickHouse inserts
- `clickhouse_insert_errors_total` (counter) - failed inserts

### Log Aggregation (Option 2b)
Consider adding:
- **Loki** for log aggregation (lightweight, integrates with Grafana)
- **Promtail** to ship logs from containers
- Or **Elasticsearch + Filebeat** for more advanced log analysis

### Additional Dashboards
- **ETL Pipeline**: Spark job metrics, data quality checks
- **MinIO/S3**: Storage usage, object count, bucket metrics
- **PostgreSQL**: Connection pool, query performance, table size
