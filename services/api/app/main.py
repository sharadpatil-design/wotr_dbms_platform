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
from .auth import get_api_key
from .retention import RETENTION_POLICIES
from .rate_limiting import limiter, RATE_LIMITS
from .cors_config import CORS_CONFIG
from .tracing import init_tracing, get_tracer, add_span_attributes, record_exception
from .structured_logging import setup_logging, get_logger, RequestLogger
from .schemas import IngestRequest, validate_payload, DataQualityCheck, ValidationResult
from .schema_evolution import get_schema_registry, AvroSerializer
from .admin import router as admin_router
from .data_explorer import router as explorer_router
from .connection_pool import (
    initialize_pools, close_all_pools,
    get_pg_connection, get_clickhouse_client, get_kafka_producer, get_redis_client
)
from .cache import CacheManager, StatsCache, warm_stats_cache, cache_result
from .clickhouse_optimization import initialize_clickhouse_optimizations

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

# Validation metrics
VALIDATION_FAILURES = Counter(
    "wotr_validation_failures_total",
    "Total validation failures",
    ["reason"]
)

DATA_QUALITY_SCORE = Histogram(
    "wotr_data_quality_score",
    "Data quality completeness score"
)

# Setup structured logging
setup_logging()
logger = get_logger(__name__)

# Global cache manager (initialized on startup)
cache_manager = None

app = FastAPI(title="WOTR Data API")

# Add rate limiter state and exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Include operational routers
app.include_router(admin_router)
app.include_router(explorer_router)

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
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    
    # Structured logging context
    with RequestLogger(logger, request_id, request.method, request.url.path):
        try:
            response = await call_next(request)
            latency = time.time() - start_time
            REQUEST_LATENCY.labels(request.method, request.url.path).observe(latency)
            REQUEST_COUNT.labels(request.method, request.url.path, response.status_code).inc()
            
            # Add request ID to response
            response.headers["X-Request-ID"] = request_id
            
            # Log response
            logger.info(
                "Request processed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "latency": latency,
                }
            )
            
            return response
        except Exception as e:
            ERROR_COUNT.labels(type(e).__name__).inc()
            logger.error(
                "Request error",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                exc_info=True
            )
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


# ---- Helper Functions (Updated to use connection pools) ----
def get_pg():
    """Get PostgreSQL connection (legacy - for initialization)."""
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
        # Use pooled connection
        client = get_clickhouse_client()
        client.execute("SELECT 1")
        return "ok"
    except Exception as e:
        return f"error: {str(e)}"


# ---- Routes ----
# Using enhanced schema from schemas.py


@app.post("/validate")
@limiter.limit("60/minute")
def validate_event(request: Request, payload: dict):
    """
    Validate event payload without ingesting
    Useful for client-side validation
    """
    tracer = get_tracer()
    with tracer.start_as_current_span("validate_payload"):
        validation_result = validate_payload(payload)
        
        if not validation_result.valid:
            VALIDATION_FAILURES.labels(reason="schema_error").inc()
        
        return {
            "valid": validation_result.valid,
            "errors": validation_result.errors,
            "warnings": validation_result.warnings
        }


@app.get("/health")
@limiter.limit(RATE_LIMITS["health"])
def health(request: Request):
    tracer = get_tracer()
    with tracer.start_as_current_span("health_check") as span:
        details = {}
        try:
            with tracer.start_as_current_span("postgres_check"):
                conn = get_pg()
                conn.close()
                postgres_status.set(1)
                details["postgres"] = "ok"
        except Exception as e:
            postgres_status.set(0)
            details["postgres"] = str(e)
            logger.error(f"Postgres health check failed: {e}")

        try:
            with tracer.start_as_current_span("minio_check"):
                _ = get_minio()
                minio_status.set(1)
                details["minio"] = "ok"
        except Exception as e:
            minio_status.set(0)
            details["minio"] = str(e)
            logger.error(f"MinIO health check failed: {e}")

        try:
            with tracer.start_as_current_span("kafka_check"):
                _ = get_kafka()
                kafka_status.set(1)
                details["kafka"] = "ok"
        except Exception as e:
            kafka_status.set(0)
            details["kafka"] = str(e)
            logger.error(f"Kafka health check failed: {e}")

        # ClickHouse health check
        with tracer.start_as_current_span("clickhouse_check"):
            clickhouse_result = check_clickhouse()
            if clickhouse_result == "ok":
                clickhouse_status.set(1)
                details["clickhouse"] = "ok"
            else:
                clickhouse_status.set(0)
                details["clickhouse"] = clickhouse_result
                logger.error(f"ClickHouse health check failed: {clickhouse_result}")

        add_span_attributes(span, **{"services_checked": len(details), "all_healthy": all(v == "ok" for v in details.values())})
        
        if all(v == "ok" for v in details.values()):
            return {"status": "ok", "details": details}
        else:
            raise HTTPException(status_code=500, detail=details)


@app.post("/ingest")
@limiter.limit(RATE_LIMITS["ingest"])
def ingest(request: Request, item: IngestRequest, api_key: str = Depends(get_api_key)):
    tracer = get_tracer()
    with tracer.start_as_current_span("ingest_event") as span:
        # Validate payload
        validation_result = validate_payload(item.payload.dict())
        if not validation_result.valid:
            VALIDATION_FAILURES.labels(reason="schema_error").inc()
            logger.warning(
                f"Validation failed",
                extra={"errors": validation_result.errors}
            )
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Validation failed",
                    "errors": validation_result.errors,
                    "warnings": validation_result.warnings
                }
            )
        
        # Calculate data quality score
        quality_score = DataQualityCheck.check_completeness(item.payload.dict())
        DATA_QUALITY_SCORE.observe(quality_score)
        
        obj_id = item.id or str(uuid.uuid4())
        ts = item.timestamp or datetime.utcnow().isoformat()
        record = {"id": obj_id, "timestamp": ts, "payload": item.payload.dict()}
        data = json.dumps(record).encode()
        key = f"raw/{obj_id}.json"
        
        add_span_attributes(
            span,
            event_id=obj_id,
            payload_size=len(data),
            bucket=MINIO_BUCKET,
            quality_score=quality_score,
            event_type=item.payload.event_type
        )
        logger.info(
            f"Ingesting event {obj_id}",
            extra={
                "event_id": obj_id,
                "size": len(data),
                "quality_score": quality_score,
                "event_type": item.payload.event_type
            }
        )

        with DB_QUERY_LATENCY.time():
            try:
                # Upload to MinIO
                with tracer.start_as_current_span("minio_upload"):
                    minio = get_minio()
                    minio.put_object(MINIO_BUCKET, key, io.BytesIO(data), len(data), "application/json")
                    logger.debug(f"Uploaded to MinIO: {key}")

                # Send to Kafka (using pooled producer)
                with tracer.start_as_current_span("kafka_publish"):
                    kafka = get_kafka_producer()
                    kafka.send(KAFKA_TOPIC, json.dumps(record).encode("utf-8"))
                    kafka.flush()
                    logger.debug(f"Published to Kafka topic: {KAFKA_TOPIC}")

                # Store metadata in Postgres (using pooled connection)
                with tracer.start_as_current_span("postgres_insert"):
                    with get_pg_connection() as conn:
                        cur = conn.cursor()
                        cur.execute("INSERT INTO ingest_meta VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING;", (obj_id, key, datetime.utcnow(), len(data)))
                        conn.commit()
                    logger.debug(f"Stored metadata in Postgres")
                    logger.debug(f"Stored metadata in Postgres")
                    
            except Exception as e:
                record_exception(span, e)
                logger.error(f"Ingest failed for {obj_id}: {e}", extra={"event_id": obj_id, "error": str(e)}, exc_info=True)
                raise

        INGEST_COUNTER.inc()
        logger.info(f"Successfully ingested event {obj_id}", extra={"event_id": obj_id})

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
    global cache_manager
    
    app_uptime.set(1)
    
    # Initialize distributed tracing
    init_tracing(app, service_name="wotr-api")
    logger.info("WOTR API starting...", extra={"service": "wotr-api"})
    
    # Initialize connection pools
    try:
        initialize_pools()
        logger.info("Connection pools initialized")
    except Exception as e:
        logger.error(f"Failed to initialize connection pools: {e}")
        raise
    
    # Initialize cache manager
    try:
        redis_client = get_redis_client()
        cache_manager = CacheManager(redis_client)
        logger.info("Cache manager initialized")
        
        # Warm cache
        warm_stats_cache(cache_manager)
        logger.info("Cache warmed")
    except Exception as e:
        logger.warning(f"Failed to initialize cache (non-fatal): {e}")
    
    # Initialize ClickHouse optimizations with retry
    max_retries = 3
    retry_delay = 2
    for attempt in range(max_retries):
        try:
            clickhouse_client = get_clickhouse_client()
            # Test connection
            clickhouse_client.execute("SELECT 1")
            initialize_clickhouse_optimizations(clickhouse_client)
            logger.info("ClickHouse optimizations initialized")
            break
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"ClickHouse not ready (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                logger.warning(f"Failed to initialize ClickHouse optimizations after {max_retries} attempts (non-fatal): {e}")
    
    # Initialize database schema
    try:
        conn = get_pg()
        conn.close()
        logger.info("Database schema initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database schema: {e}")
    
    logger.info("WOTR API started successfully", extra={"service": "wotr-api"})


@app.on_event("shutdown")
def on_shutdown():
    """Clean up resources on shutdown."""
    logger.info("WOTR API shutting down...")
    
    try:
        close_all_pools()
        logger.info("Connection pools closed")
    except Exception as e:
        logger.error(f"Error closing connection pools: {e}")
    
    app_uptime.set(0)
    logger.info("WOTR API stopped")
