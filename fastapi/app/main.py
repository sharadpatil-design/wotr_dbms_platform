import io
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os, uuid, json
from datetime import datetime
from minio import Minio
from kafka import KafkaProducer
import psycopg2
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response

app = FastAPI(title="WOTR Data API")

ingest_counter = Counter("wotr_ingest_total", "Number of ingested events")

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

class IngestPayload(BaseModel):
    id: str | None = None
    timestamp: str | None = None
    payload: dict

def get_pg():
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
    client = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)
    if not client.bucket_exists(MINIO_BUCKET):
        client.make_bucket(MINIO_BUCKET)
    return client

def get_kafka():
    return KafkaProducer(bootstrap_servers=[KAFKA_BOOTSTRAP],
                         value_serializer=lambda v: json.dumps(v).encode("utf-8"))

@app.get("/health")
def health():
    try:
        conn = get_pg()
        conn.close()
        _ = get_minio()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "ok"}

@app.post("/ingest")
def ingest(item: IngestPayload):
    obj_id = item.id or str(uuid.uuid4())
    ts = item.timestamp or datetime.utcnow().isoformat()
    record = {"id": obj_id, "timestamp": ts, "payload": item.payload}
    data = json.dumps(record).encode()
    key = f"raw/{obj_id}.json"

    minio = get_minio()
    minio.put_object(MINIO_BUCKET, key, data=io.BytesIO(data), length=len(data), content_type="application/json")

    kafka = get_kafka()
    # Explicitly serialize to bytes to avoid kafka-python asserting non-bytes payloads
    kafka.send(KAFKA_TOPIC, json.dumps(record).encode("utf-8"))
    kafka.flush()

    conn = get_pg()
    cur = conn.cursor()
    cur.execute("INSERT INTO ingest_meta VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING;", (obj_id, key, datetime.utcnow(), len(data)))
    conn.commit()
    conn.close()

    ingest_counter.inc()
    return {"id": obj_id, "object_key": key}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
