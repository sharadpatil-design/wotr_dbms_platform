import os, json, time
from kafka import KafkaConsumer
from clickhouse_driver import Client

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "redpanda:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "ingest-events")
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "clickhouse")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", 9000))
CLICKHOUSE_DB = os.getenv("CLICKHOUSE_DB", "wotr")
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")

print(f"[Consumer] Starting consumer on {KAFKA_BOOTSTRAP}, topic {KAFKA_TOPIC}")
print(f"[Consumer] ClickHouse: {CLICKHOUSE_HOST}:{CLICKHOUSE_PORT}, DB: {CLICKHOUSE_DB}, User: {CLICKHOUSE_USER}")

time.sleep(10)
client = Client(host=CLICKHOUSE_HOST, port=CLICKHOUSE_PORT, user=CLICKHOUSE_USER, password=CLICKHOUSE_PASSWORD)

client.execute(f"CREATE DATABASE IF NOT EXISTS {CLICKHOUSE_DB}")
client.execute(f"""
CREATE TABLE IF NOT EXISTS {CLICKHOUSE_DB}.ingested_data (
    id String,
    timestamp String,
    payload String,
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY id
""")

consumer = KafkaConsumer(
    KAFKA_TOPIC,
    bootstrap_servers=[KAFKA_BOOTSTRAP],
    auto_offset_reset="earliest",
    enable_auto_commit=True,
    group_id="wotr-consumer",
    value_deserializer=lambda m: json.loads(m.decode("utf-8"))
)

for msg in consumer:
    record = msg.value
    try:
        client.execute(
            f"INSERT INTO {CLICKHOUSE_DB}.ingested_data (id, timestamp, payload) VALUES",
            [(record.get("id", ""), record.get("timestamp", ""), json.dumps(record.get("payload", {})))]
        )
        print(f"[Consumer] Inserted record {record.get('id')}")
    except Exception as e:
        print("[Consumer] Failed insert:", e)
