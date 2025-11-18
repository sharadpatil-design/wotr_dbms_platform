## Purpose
Short, actionable guidance for AI coding agents working on this repository. Focus on the runtime architecture, developer workflows, integration points, and concrete code examples found in the tree.

## Big picture (what this repo runs)
- Local data platform scaffold (dev-only): services deployed via `docker-compose.yml`.
- Key components: Redpanda (Kafka), PostgreSQL, MinIO (S3), ClickHouse, Prometheus + Grafana, FastAPI ingestion API, a Kafka consumer that writes to ClickHouse, a PySpark ETL job, and Superset for visualization.
- Primary data flow:
  1. Client -> `POST /ingest` on FastAPI (`services/api/app/main.py`) which
     - uploads the event JSON to MinIO (S3) and
     - publishes an event to Kafka (topic `ingest-events`) and
     - writes metadata to Postgres.
  2. `services/consumer/consumer.py` consumes Kafka `ingest-events` and inserts into ClickHouse.
  3. ETL (`etl/pyspark/etl_job.py`) reads raw JSON from MinIO (`s3a://raw/`) and writes curated Parquet back to MinIO.

## Developer workflows (concrete)
- Bring everything up (uses Makefile):
```powershell
make build
make up
```
- Run a test ingest (uses `tools/ingest_test.py`):
```powershell
make ingest
```
- Trigger the PySpark job (uses docker-compose service):
```powershell
make run-etl
```
- Stop + remove volumes:
```powershell
make down
```

## Quick local API example
- Example event shape (JSON):
```json
{"payload": {"example": "hello", "value": 123}}
```
- Send an event (to test the pipeline):
```bash
curl -X POST http://localhost:8000/ingest -H 'Content-Type: application/json' -d '{"payload":{"example":"hello"}}'
```

## Project-specific patterns & conventions
- Services use direct clients (psycopg2, `minio.Minio`, `kafka.KafkaProducer`, `clickhouse_driver`) rather than ORMs or frameworks; look for `get_pg()`, `get_minio()` and `get_kafka()` helpers in `services/api/app/main.py`.
- Tables are created on-demand during startup (see `get_pg()` and ClickHouse `CREATE TABLE IF NOT EXISTS` in `services/consumer/consumer.py`).
- Prometheus metrics are emitted from the FastAPI app; alert rules live in `observability/alerts.yml` and scraping config in `observability/prometheus.yml` (see `docker-compose.yml` mount).
- ETL uses Spark with S3A to talk to MinIO — configure `MINIO_ENDPOINT`, `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` (see `etl/pyspark/etl_job.py` and service env in `docker-compose.yml`).

## Integration points & env vars (most important)
- `MINIO_ENDPOINT`, `MINIO_BUCKET`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` — MinIO S3 access used by FastAPI and Spark.
- `KAFKA_BOOTSTRAP` / `KAFKA_TOPIC` — Kafka broker and topic names (Redpanda).
- `POSTGRES_*` — host/port/user/password used by ingest metadata.
- `CLICKHOUSE_*` — host/port/db used by the consumer.

## Useful files to inspect (one-liners)
- `docker-compose.yml` — how services are wired and which env vars are injected.
- `Makefile` — simple dev commands (`build`, `up`, `ingest`, `run-etl`, `down`).
- `services/api/app/main.py` — ingestion API, MinIO + Kafka + Postgres integration, metrics endpoints.
- `services/consumer/consumer.py` — Kafka consumer and ClickHouse inserts.
- `etl/pyspark/etl_job.py` — PySpark job reading from `s3a://raw/` and writing `s3a://curated/`.
- `observability/alerts.yml` — Prometheus alerting rules (p95 latency, service-down alerts).

## When editing code, prefer these small checks
- Run `make up` and use `make ingest` to exercise the full pipeline end-to-end.
- Verify `/metrics` (FastAPI) and `observability/alerts.yml` metric names if adding metrics.
- If changing schema, update the ClickHouse table DDL in `services/consumer/consumer.py` and any places that read from it.

If anything here is unclear or you want the instructions to emphasize different parts (testing, CI, or production hardening), say which area and I will iterate.

## Grafana dashboards (what's included)
- This repo includes JSON dashboard exports you can import into Grafana for immediate observability:
  - `fastapi/wotr_fastapi_dashboard.json` — FastAPI-focused dashboard (request rates, latency, errors).
  - `observability/fastapi_system_health.json` — service health panels (postgres, clickhouse, kafka, minio gauges).
  - `services/service_health_dashboard.json` — cross-service health overview.
- Metrics used by dashboards (look for these in code): `fastapi_request_duration_seconds`, `fastapi_error_total`, `wotr_ingest_total`, `postgres_status`, `clickhouse_status`, `kafka_status`, `minio_status`.

## End-to-end ingest trace (quick guide)
Follow these steps to exercise and trace a single event through the pipeline:
1. Start the platform:
```powershell
make build
make up
```
2. POST a test event (or run `make ingest`):
```powershell
curl -X POST http://localhost:8000/ingest -H "Content-Type: application/json" -d '{"payload":{"example":"hello"}}'
```
3. Verify FastAPI accepted it: check `fastapi` container logs or hit `http://localhost:8000/health` and `http://localhost:8000/metrics`.
4. Confirm object in MinIO: list bucket `raw-data` (MinIO UI at http://localhost:9000 or via `mc`), key path is `raw/<id>.json` (see `services/api/app/main.py`).
5. Confirm Kafka message: tail the `consumer` logs (or `docker-compose logs -f consumer`) — `services/consumer/consumer.py` prints inserted record ids.
6. Confirm ClickHouse row: connect to ClickHouse HTTP port (8123) or use `clickhouse-client` and query `SELECT * FROM wotr.ingested_data ORDER BY created_at DESC LIMIT 10`.
7. Run ETL to create curated parquet if needed:
```powershell
make run-etl
```
8. Check curated Parquet at `s3a://<MINIO_BUCKET>/curated/` (MinIO UI or S3 client).

## Troubleshooting quick checks
- Containers not coming up: run `docker-compose ps` and `docker-compose logs <service>` (e.g., `docker-compose logs fastapi`).
- FastAPI errors / 500 on `/ingest`: inspect `services/api/app/main.py` for MinIO/Kafka/Postgres connection logic; check env vars in `docker-compose.yml` (POSTGRES_*, MINIO_*, KAFKA_*).
- Missing MinIO objects: confirm `MINIO_BUCKET` env and that `get_minio()` creates the bucket (see `services/api/app/main.py` and `services/consumer/consumer.py`).
- Kafka connectivity issues: ensure `redpanda` is healthy and `KAFKA_BOOTSTRAP` matches (default `redpanda:9092`). Check `consumer` logs for errors.
- ClickHouse inserts failing: look at the consumer logs for stack traces; ensure ClickHouse ports/credentials match `docker-compose.yml` and `services/consumer/consumer.py` DDL.
- Prometheus / Grafana metrics missing: confirm Prometheus is configured (`observability/prometheus.yml`) and that FastAPI metrics endpoint `/metrics` is reachable.

Files to check when troubleshooting:
- FastAPI: `services/api/app/main.py` (ingest flow, metrics, env vars)
- Consumer: `services/consumer/consumer.py` (Kafka consumer, ClickHouse inserts)
- ETL: `etl/pyspark/etl_job.py` (S3A config)
- Docker wiring: `docker-compose.yml` and `Makefile`
- Dashboards: `fastapi/wotr_fastapi_dashboard.json`, `observability/fastapi_system_health.json`, `services/service_health_dashboard.json`

---
Updated the instructions to reference Grafana dashboards and add a short E2E trace and troubleshooting tips. Tell me if you want the Dockerfile/build tips and CI guidance added next (I can apply those as well).

## Dockerfile & build tips
- Dockerfiles to inspect and optimize:
  - `services/api/Dockerfile` (FastAPI API image)
  - `fastapi/Dockerfile` (alternate FastAPI image used for local dev)
  - `services/consumer/Dockerfile` (Kafka consumer)
  - `etl/pyspark/Dockerfile` (Spark job image)
- Practical tips when editing Dockerfiles in this repo:
  - Put dependency installation (pip install -r requirements.txt) before copying application code so layer cache is effective.
  - Add a `.dockerignore` to exclude local artifacts (`.venv`, `__pycache__`, `.git`) to speed context uploads.
  - Use multi-stage builds for the ETL image when packaging Spark job artifacts to keep images small.
  - Pin base images (e.g., `python:3.11-slim`) to avoid unexpected changes during rebuilds.
  - For local builds on Apple Silicon or CI, use `--platform linux/amd64` or `docker buildx` when necessary (see Makefile if you add a `buildx` target).
  - Cache Python wheels between builds in CI by mounting a cache directory or using the `pip --cache-dir` option in build steps.

## CI & tests guidance (minimal, runnable)
- Goals: fast feedback on build + smoke test (do images build, core endpoints respond).
- Minimal GitHub Actions workflow (recommendation):
  1. Checkout repository + set up QEMU/buildx.
  2. Build images (`make build`) using `docker/build-push-action` or run `docker-compose build`.
  3. Bring up a minimal set of services for a smoke test: `fastapi`, `minio`, `redpanda`, and `postgres` (either via `docker-compose up -d fastapi minio redpanda postgres` or by running the built images directly in the job).
  4. Run a health-check script that calls `/health` and `/metrics`, then a single `/ingest` POST and verify a 200 response.
  5. Tear down containers.
- Keep CI fast: avoid bringing up stateful services like ClickHouse or Superset in the same job unless necessary — run them in a separate integration job.
- Add a small `ci/smoke_test.py` (or use `tools/ingest_test.py`) that the workflow invokes to validate the ingest path.

## Example CI checklist
- Lint (optional) — run `flake8` or `ruff` against Python code.
- Build images — `make build`.
- Smoke start — `docker-compose up -d fastapi minio redpanda postgres`.
- Smoke test — run `python3 tools/ingest_test.py` and curl `/health`.
- Teardown — `docker-compose down --volumes`.

---
Applied Dockerfile and CI guidance. If you want, I can implement a starter GitHub Actions workflow file (`.github/workflows/ci.yml`) and a small `ci/smoke_test.py` derived from `tools/ingest_test.py` next; tell me to proceed and I'll add them.
