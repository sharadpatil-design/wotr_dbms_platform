# 🌾 WOTR Local Data Platform (Open Source Edition)

**Components:** PostgreSQL, MinIO, Redpanda (Kafka), ClickHouse, Prometheus, Grafana, FastAPI, PySpark, Superset

## Setup
1. Install Docker + Docker Compose.
2. Copy `.env` as needed.
3. Build and start:
```bash
make build
make up
```
4. Test ingestion:
```bash
make ingest
```
5. Run ETL:
```bash
make run-etl
```

### Services
| Service | Port | Notes |
|---------|------|-------|
| FastAPI | 8000 | `/health`, `/ingest`, `/metrics` |
| MinIO | 9000 | admin/minioadmin |
| Grafana | 3000 | admin/admin |
| Prometheus | 9090 | metrics |
| Superset | 8088 | admin/admin (created at startup) |

Stop everything:
```bash
make down
```

Notes:
- This is a local dev scaffold. For production, use hardened configs and persistent backups.
