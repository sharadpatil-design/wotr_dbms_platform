import io, os, uuid, json, time, logging
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from minio import Minio, S3Error
from kafka import KafkaProducer
from clickhouse_driver import Client as ClickHouseClient
import psycopg2
from prometheus_client import (
    Counter, Histogram, Gauge,
    generate_latest, CONTENT_TYPE_LATEST
)
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from auth import get_api_key
from retention import RETENTION_POLICIES
from rate_limiting import limiter, RATE_LIMITS
from cors_config import CORS_CONFIG

# --- Prometheus Metrics ---
REQUEST_COUNT = Counter(
    "fastapi_requests_total", "Total number of HTTP requests",
    ["method", "endpoint", "http_status"]
)

REQUEST_LATENCY = Histogram(
    "fastapi_request_duration_seconds", "Request latency (seconds)",
    ["method", "endpoint"]
)

DB_QUERY_LATENCY = Histogram(
    "fastapi_db_query_duration_seconds", "Database query latency (seconds)"
)

ERROR_COUNT = Counter(
    "fastapi_error_total", "Total number of exceptions raised", ["type"]
)

# Gauges for service health
postgres_status = Gauge("postgres_status", "Postgres connection status (1=up, 0=down)")
minio_status = Gauge("minio_status", "MinIO connection status (1=up, 0=down)")
kafka_status = Gauge("kafka_status", "Kafka connection status (1=up, 0=down)")
clickhouse_status = Gauge("clickhouse_status", "ClickHouse connection status (1=up, 0=down)")
app_uptime = Gauge("app_uptime", "FastAPI app uptime indicator (1=running)")

# Ingest counter
INGEST_COUNTER = Counter("wotr_ingest_total", "Number of ingested events")

logger = logging.getLogger(__name__)
app = FastAPI(title="WOTR Data API")

# Add rate limiter state and exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_CONFIG["allow_origins"],
    allow_credentials=CORS_CONFIG["allow_credentials"],
    allow_methods=CORS_CONFIG["allow_methods"],
    allow_headers=CORS_CONFIG["allow_headers"],
    expose_headers=CORS_CONFIG["expose_headers"],
    max_age=CORS_CONFIG["max_age"],
)

# Middleware for request tracking
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start_time = time.time()
    try:
        response = await call_next(request)
        latency = time.time() - start_time
        REQUEST_LATENCY.labels(request.method, request.url.path).observe(latency)
        REQUEST_COUNT.labels(request.method, request.url.path, response.status_code).inc()
        return response
    except Exception as e:
        ERROR_COUNT.labels(type(e).__name__).inc()
        raise


# ---- Environment Variables ----
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "raw-data")

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "redpanda:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "ingest-events")

POSTGRES = {
    "host": os.getenv("POSTGRES_HOST", "postgres"),
    "port": int(os.getenv("POSTGRES_PORT", 5432)),
    "dbname": os.getenv("POSTGRES_DB", "wotrdb"),
    "user": os.getenv("POSTGRES_USER", "wotr"),
    "password": os.getenv("POSTGRES_PASSWORD", "wotrpass"),
}


# ---- Helper Functions ----
def get_pg():
    with DB_QUERY_LATENCY.time():
        conn = psycopg2.connect(**POSTGRES)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ingest_meta (
              id TEXT PRIMARY KEY,
              object_key TEXT,
              created_at TIMESTAMP,
              payload_size INT
            );
        """)
        conn.commit()
        return conn


def get_minio():
    endpoint = MINIO_ENDPOINT.replace("http://", "").replace("https://", "")
    client = Minio(endpoint, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)
    if not client.bucket_exists(MINIO_BUCKET):
        client.make_bucket(MINIO_BUCKET)
    return client


def get_kafka():
    producer = KafkaProducer(bootstrap_servers=[KAFKA_BOOTSTRAP])
    return producer


def check_clickhouse():
    try:
        client = ClickHouseClient(
            host=os.getenv("CLICKHOUSE_HOST", "clickhouse"),
            port=int(os.getenv("CLICKHOUSE_PORT", 9000)),
            user=os.getenv("CLICKHOUSE_USER", "default"),
            password=os.getenv("CLICKHOUSE_PASSWORD", "")
        )
        client.execute("SELECT 1")
        return "ok"
    except Exception as e:
        return f"error: {str(e)}"


# ---- Routes ----
class IngestPayload(BaseModel):
    id: str | None = None
    timestamp: str | None = None
    payload: dict


@app.get("/health")
@limiter.limit(RATE_LIMITS["health"])
def health(request: Request):
    details = {}
    try:
        conn = get_pg()
        conn.close()
        postgres_status.set(1)
        details["postgres"] = "ok"
    except Exception as e:
        postgres_status.set(0)
        details["postgres"] = str(e)

    try:
        _ = get_minio()
        minio_status.set(1)
        details["minio"] = "ok"
    except Exception as e:
        minio_status.set(0)
        details["minio"] = str(e)

    try:
        _ = get_kafka()
        kafka_status.set(1)
        details["kafka"] = "ok"
    except Exception as e:
        kafka_status.set(0)
        details["kafka"] = str(e)

    # ClickHouse health check
    clickhouse_result = check_clickhouse()
    if clickhouse_result == "ok":
        clickhouse_status.set(1)
        details["clickhouse"] = "ok"
    else:
        clickhouse_status.set(0)
        details["clickhouse"] = clickhouse_result

    if all(v == "ok" for v in details.values()):
        return {"status": "ok", "details": details}
    else:
        raise HTTPException(status_code=500, detail=details)


@app.post("/ingest")
@limiter.limit(RATE_LIMITS["ingest"])
def ingest(request: Request, item: IngestPayload, api_key: str = Depends(get_api_key)):
    obj_id = item.id or str(uuid.uuid4())
    ts = item.timestamp or datetime.utcnow().isoformat()
    record = {"id": obj_id, "timestamp": ts, "payload": item.payload}
    data = json.dumps(record).encode()
    key = f"raw/{obj_id}.json"

    with DB_QUERY_LATENCY.time():
        minio = get_minio()
        minio.put_object(MINIO_BUCKET, key, io.BytesIO(data), len(data), "application/json")

        kafka = get_kafka()
        # Serialize record explicitly to bytes so kafka-python accepts the payload
        kafka.send(KAFKA_TOPIC, json.dumps(record).encode("utf-8"))
        kafka.flush()

        conn = get_pg()
        cur = conn.cursor()
        cur.execute("INSERT INTO ingest_meta VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING;", (obj_id, key, datetime.utcnow(), len(data)))
        conn.commit()
        conn.close()

    INGEST_COUNTER.inc()

    return {"id": obj_id, "object_key": key}


@app.get("/metrics")
@limiter.limit(RATE_LIMITS["metrics"])
def metrics(request: Request):
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/retention-policies")
@limiter.limit(RATE_LIMITS["retention"])
def get_retention_policies(request: Request, api_key: str = Depends(get_api_key)):
    """Get current retention policy configuration"""
    return {
        "policies": RETENTION_POLICIES,
        "note": "Run retention_cleanup.py script to apply policies"
    }


@app.on_event("startup")
def on_startup():
    app_uptime.set(1)
