"""
Enhanced consumer with validation, DLQ, and retry logic
"""
import os, json, time, sys, io
from kafka import KafkaConsumer, KafkaProducer
from clickhouse_driver import Client
from minio import Minio
from prometheus_client import Counter, Histogram, Gauge, start_http_server
from pythonjsonlogger import jsonlogger
import logging
import jsonschema
from dead_letter_queue import DeadLetterQueue, RetryableMessage, create_dlq_metrics

# --- Structured Logging Setup ---
class CustomJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
        log_record['timestamp'] = record.created
        log_record['level'] = record.levelname
        log_record['service'] = 'wotr-consumer'
        log_record['environment'] = os.getenv('ENVIRONMENT', 'development')

log_format = os.getenv("LOG_FORMAT", "json").lower()
if log_format == "json":
    formatter = CustomJsonFormatter('%(timestamp)s %(level)s %(name)s %(message)s')
else:
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(formatter)
logger.addHandler(handler)

# --- Prometheus Metrics ---
MESSAGES_CONSUMED = Counter(
    "consumer_messages_consumed_total",
    "Total number of messages consumed from Kafka"
)

MESSAGES_PROCESSED = Counter(
    "consumer_messages_processed_total",
    "Total number of messages successfully processed",
    ["status"]  # success, error, retried, dlq
)

PROCESSING_LATENCY = Histogram(
    "consumer_processing_duration_seconds",
    "Time taken to process a message"
)

CLICKHOUSE_INSERT_LATENCY = Histogram(
    "consumer_clickhouse_insert_duration_seconds",
    "Time taken to insert into ClickHouse"
)

VALIDATION_FAILURES = Counter(
    "consumer_validation_failures_total",
    "Total validation failures",
    ["reason"]
)

CONSUMER_ERRORS = Counter(
    "consumer_errors_total",
    "Total number of processing errors",
    ["error_type"]
)

# DLQ metrics
dlq_metrics = create_dlq_metrics()

# Start Prometheus metrics server
METRICS_PORT = int(os.getenv("METRICS_PORT", 8001))
start_http_server(METRICS_PORT)
logger.info(f"Prometheus metrics server started on port {METRICS_PORT}")

# --- Environment Variables ---
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "redpanda:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "ingest-events")
KAFKA_DLQ_TOPIC = os.getenv("KAFKA_DLQ_TOPIC", "dlq-events")
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "clickhouse")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", 9000))
CLICKHOUSE_DB = os.getenv("CLICKHOUSE_DB", "wotr")
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

logger.info(
    "Starting enhanced consumer with DLQ support",
    extra={
        "kafka_bootstrap": KAFKA_BOOTSTRAP,
        "kafka_topic": KAFKA_TOPIC,
        "dlq_topic": KAFKA_DLQ_TOPIC,
        "clickhouse_host": CLICKHOUSE_HOST,
        "max_retries": MAX_RETRIES,
    }
)

# Wait for services
time.sleep(10)

# --- Setup Components ---
logger.info("Connecting to ClickHouse")
clickhouse_client = Client(
    host=CLICKHOUSE_HOST,
    port=CLICKHOUSE_PORT,
    user=CLICKHOUSE_USER,
    password=CLICKHOUSE_PASSWORD
)

# Create database and table
logger.info(f"Creating database {CLICKHOUSE_DB}")
clickhouse_client.execute(f"CREATE DATABASE IF NOT EXISTS {CLICKHOUSE_DB}")

logger.info(f"Creating table {CLICKHOUSE_DB}.ingested_data")
clickhouse_client.execute(f"""
CREATE TABLE IF NOT EXISTS {CLICKHOUSE_DB}.ingested_data (
    id String,
    timestamp String,
    payload String,
    event_type String,
    source String,
    validation_status String,
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (event_type, created_at, id)
PARTITION BY toYYYYMM(created_at)
""")

# Setup MinIO
logger.info("Connecting to MinIO")
minio_endpoint = MINIO_ENDPOINT.replace("http://", "").replace("https://", "")
minio_client = Minio(
    minio_endpoint,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)

# Setup Kafka producer for DLQ
kafka_producer = KafkaProducer(
    bootstrap_servers=[KAFKA_BOOTSTRAP],
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

# Initialize DLQ
dlq = DeadLetterQueue(
    minio_client=minio_client,
    kafka_producer=kafka_producer,
    dlq_bucket="dead-letters",
    dlq_topic=KAFKA_DLQ_TOPIC,
    max_retries=MAX_RETRIES
)

logger.info("DLQ initialized successfully")

# --- Schema validation ---
PAYLOAD_SCHEMA = {
    "type": "object",
    "required": ["event_type", "source"],
    "properties": {
        "event_type": {"type": "string"},
        "source": {"type": "string"},
        "user_id": {"type": ["string", "null"]},
        "session_id": {"type": ["string", "null"]},
        "data": {"type": "object"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "version": {"type": "string"}
    }
}

def validate_message(record: dict) -> tuple[bool, str]:
    """Validate message structure"""
    try:
        payload = record.get("payload", {})
        jsonschema.validate(instance=payload, schema=PAYLOAD_SCHEMA)
        return True, "valid"
    except jsonschema.ValidationError as e:
        return False, f"Schema validation failed: {e.message}"
    except Exception as e:
        return False, f"Validation error: {str(e)}"

def process_message(record: dict, retry_count: int = 0):
    """Process a single message with validation and error handling"""
    record_id = record.get("id", "unknown")
    
    # Validate message
    is_valid, validation_msg = validate_message(record)
    if not is_valid:
        VALIDATION_FAILURES.labels(reason="schema_error").inc()
        logger.warning(
            f"Message validation failed: {validation_msg}",
            extra={"record_id": record_id, "validation_error": validation_msg}
        )
        # Send invalid messages to DLQ
        dlq.send_to_dlq(
            record,
            ValueError(validation_msg),
            retry_count=0,
            metadata={"validation_status": "failed"}
        )
        MESSAGES_PROCESSED.labels(status="dlq").inc()
        dlq_metrics["messages"].labels(error_type="validation_error").inc()
        return
    
    # Extract payload fields
    payload = record.get("payload", {})
    event_type = payload.get("event_type", "unknown")
    source = payload.get("source", "unknown")
    
    # Insert into ClickHouse
    with CLICKHOUSE_INSERT_LATENCY.time():
        clickhouse_client.execute(
            f"INSERT INTO {CLICKHOUSE_DB}.ingested_data (id, timestamp, payload, event_type, source, validation_status) VALUES",
            [(
                record.get("id", ""),
                record.get("timestamp", ""),
                json.dumps(payload),
                event_type,
                source,
                "valid"
            )]
        )
    
    logger.info(
        "Message processed successfully",
        extra={
            "record_id": record_id,
            "event_type": event_type,
            "source": source,
            "retry_count": retry_count
        }
    )

# --- Kafka Consumer Setup ---
logger.info(f"Creating Kafka consumer for topic {KAFKA_TOPIC}")
consumer = KafkaConsumer(
    KAFKA_TOPIC,
    bootstrap_servers=[KAFKA_BOOTSTRAP],
    auto_offset_reset="earliest",
    enable_auto_commit=True,
    group_id="wotr-consumer",
    value_deserializer=lambda m: json.loads(m.decode("utf-8"))
)

logger.info("Consumer ready with DLQ support, starting message processing loop")

# --- Message Processing Loop with Retry ---
retry_queue: dict[str, RetryableMessage] = {}

for msg in consumer:
    MESSAGES_CONSUMED.inc()
    record = msg.value
    record_id = record.get("id", "unknown")
    
    logger.debug(
        "Received message",
        extra={
            "record_id": record_id,
            "partition": msg.partition,
            "offset": msg.offset,
        }
    )
    
    with PROCESSING_LATENCY.time():
        # Check if this is a retry
        retryable = retry_queue.get(record_id)
        if retryable:
            retry_count = retryable.retry_count
            logger.info(f"Retrying message {record_id} (attempt {retry_count + 1})")
            dlq_metrics["retries"].inc()
        else:
            retry_count = 0
            retryable = RetryableMessage(record, max_retries=MAX_RETRIES)
        
        try:
            process_message(record, retry_count)
            MESSAGES_PROCESSED.labels(status="success").inc()
            
            # Remove from retry queue if present
            if record_id in retry_queue:
                del retry_queue[record_id]
            
        except Exception as e:
            error_type = type(e).__name__
            CONSUMER_ERRORS.labels(error_type=error_type).inc()
            retryable.record_error(e)
            
            logger.error(
                "Failed to process message",
                extra={
                    "record_id": record_id,
                    "partition": msg.partition,
                    "offset": msg.offset,
                    "error": str(e),
                    "error_type": error_type,
                    "retry_count": retry_count,
                },
                exc_info=True
            )
            
            # Retry logic
            if retryable.can_retry():
                retryable.increment_retry()
                retry_queue[record_id] = retryable
                MESSAGES_PROCESSED.labels(status="retried").inc()
                
                # Wait with exponential backoff
                backoff_delay = retryable.get_backoff_delay()
                logger.info(f"Scheduling retry for {record_id} in {backoff_delay}s")
                time.sleep(backoff_delay)
            else:
                # Send to DLQ after exhausting retries
                dlq_id = dlq.send_to_dlq(
                    record,
                    e,
                    retry_count=retry_count,
                    metadata={"partition": msg.partition, "offset": msg.offset}
                )
                MESSAGES_PROCESSED.labels(status="dlq").inc()
                dlq_metrics["messages"].labels(error_type=error_type).inc()
                
                # Remove from retry queue
                if record_id in retry_queue:
                    del retry_queue[record_id]
                
                logger.error(f"Message {record_id} sent to DLQ: {dlq_id}")
