"""
Enhanced consumer with Prometheus metrics and structured logging
"""
import os, json, time, sys
from kafka import KafkaConsumer
from clickhouse_driver import Client
from prometheus_client import Counter, Histogram, Gauge, start_http_server
from pythonjsonlogger import jsonlogger
import logging

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
    ["status"]  # success, error
)

PROCESSING_LATENCY = Histogram(
    "consumer_processing_duration_seconds",
    "Time taken to process a message"
)

CLICKHOUSE_INSERT_LATENCY = Histogram(
    "consumer_clickhouse_insert_duration_seconds",
    "Time taken to insert into ClickHouse"
)

CONSUMER_LAG = Gauge(
    "consumer_lag",
    "Estimated consumer lag (messages behind)"
)

CONSUMER_ERRORS = Counter(
    "consumer_errors_total",
    "Total number of processing errors",
    ["error_type"]
)

# Start Prometheus metrics server
METRICS_PORT = int(os.getenv("METRICS_PORT", 8001))
start_http_server(METRICS_PORT)
logger.info(f"Prometheus metrics server started on port {METRICS_PORT}")

# --- Environment Variables ---
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "redpanda:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "ingest-events")
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "clickhouse")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", 9000))
CLICKHOUSE_DB = os.getenv("CLICKHOUSE_DB", "wotr")
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")

logger.info(
    "Starting consumer",
    extra={
        "kafka_bootstrap": KAFKA_BOOTSTRAP,
        "kafka_topic": KAFKA_TOPIC,
        "clickhouse_host": CLICKHOUSE_HOST,
        "clickhouse_db": CLICKHOUSE_DB,
    }
)

# Wait for services to be ready
time.sleep(10)

# --- ClickHouse Setup ---
logger.info("Connecting to ClickHouse")
client = Client(
    host=CLICKHOUSE_HOST,
    port=CLICKHOUSE_PORT,
    user=CLICKHOUSE_USER,
    password=CLICKHOUSE_PASSWORD
)

# Create database and table
logger.info(f"Creating database {CLICKHOUSE_DB}")
client.execute(f"CREATE DATABASE IF NOT EXISTS {CLICKHOUSE_DB}")

logger.info(f"Creating table {CLICKHOUSE_DB}.ingested_data")
client.execute(f"""
CREATE TABLE IF NOT EXISTS {CLICKHOUSE_DB}.ingested_data (
    id String,
    timestamp String,
    payload String,
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY id
""")

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

logger.info("Consumer ready, starting message processing loop")

# --- Message Processing Loop ---
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
        try:
            # Insert into ClickHouse
            with CLICKHOUSE_INSERT_LATENCY.time():
                client.execute(
                    f"INSERT INTO {CLICKHOUSE_DB}.ingested_data (id, timestamp, payload) VALUES",
                    [(
                        record.get("id", ""),
                        record.get("timestamp", ""),
                        json.dumps(record.get("payload", {}))
                    )]
                )
            
            MESSAGES_PROCESSED.labels(status="success").inc()
            
            logger.info(
                "Message processed successfully",
                extra={
                    "record_id": record_id,
                    "partition": msg.partition,
                    "offset": msg.offset,
                }
            )
            
        except Exception as e:
            error_type = type(e).__name__
            MESSAGES_PROCESSED.labels(status="error").inc()
            CONSUMER_ERRORS.labels(error_type=error_type).inc()
            
            logger.error(
                "Failed to process message",
                extra={
                    "record_id": record_id,
                    "partition": msg.partition,
                    "offset": msg.offset,
                    "error": str(e),
                    "error_type": error_type,
                },
                exc_info=True
            )
