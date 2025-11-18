"""
Data retention policy configuration
Defines TTL and cleanup rules for different data stores
"""
import os
from datetime import timedelta

# ClickHouse retention policies
CLICKHOUSE_RETENTION_DAYS = int(os.getenv("CLICKHOUSE_RETENTION_DAYS", "90"))

# MinIO retention policies
MINIO_RAW_RETENTION_DAYS = int(os.getenv("MINIO_RAW_RETENTION_DAYS", "30"))
MINIO_CURATED_RETENTION_DAYS = int(os.getenv("MINIO_CURATED_RETENTION_DAYS", "365"))

# PostgreSQL retention policies
POSTGRES_METADATA_RETENTION_DAYS = int(os.getenv("POSTGRES_METADATA_RETENTION_DAYS", "180"))

# Retention policy definitions
RETENTION_POLICIES = {
    "clickhouse": {
        "enabled": os.getenv("CLICKHOUSE_RETENTION_ENABLED", "true").lower() == "true",
        "retention_days": CLICKHOUSE_RETENTION_DAYS,
        "table": "wotr.ingested_data",
        "timestamp_column": "created_at",
    },
    "minio_raw": {
        "enabled": os.getenv("MINIO_RAW_RETENTION_ENABLED", "true").lower() == "true",
        "retention_days": MINIO_RAW_RETENTION_DAYS,
        "bucket": "raw-data",
        "prefix": "raw/",
    },
    "minio_curated": {
        "enabled": os.getenv("MINIO_CURATED_RETENTION_ENABLED", "false").lower() == "true",
        "retention_days": MINIO_CURATED_RETENTION_DAYS,
        "bucket": "raw-data",
        "prefix": "curated/",
    },
    "postgres_metadata": {
        "enabled": os.getenv("POSTGRES_METADATA_RETENTION_ENABLED", "true").lower() == "true",
        "retention_days": POSTGRES_METADATA_RETENTION_DAYS,
        "table": "ingest_meta",
        "timestamp_column": "created_at",
    },
}


def get_retention_sql(table: str, timestamp_column: str, days: int) -> str:
    """Generate SQL for retention policy deletion"""
    return f"""
        DELETE FROM {table}
        WHERE {timestamp_column} < now() - INTERVAL '{days} days'
    """


def get_clickhouse_ttl_sql(table: str, timestamp_column: str, days: int) -> str:
    """Generate ClickHouse TTL modification SQL"""
    return f"""
        ALTER TABLE {table}
        MODIFY TTL {timestamp_column} + INTERVAL {days} DAY
    """
