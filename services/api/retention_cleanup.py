#!/usr/bin/env python3
"""
Data retention cleanup script
Executes retention policies across ClickHouse, MinIO, and PostgreSQL
"""
import os
import sys
from datetime import datetime, timedelta
from clickhouse_driver import Client as ClickHouseClient
import psycopg2
from minio import Minio
from minio.deleteobjects import DeleteObject

# Add app directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))
from retention import RETENTION_POLICIES, get_retention_sql

# Connection parameters
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "clickhouse")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", 9000))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "wotr")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "wotrpass")

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))
POSTGRES_DB = os.getenv("POSTGRES_DB", "wotr")
POSTGRES_USER = os.getenv("POSTGRES_USER", "admin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "admin")

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000").replace("http://", "").replace("https://", "")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")


def cleanup_clickhouse():
    """Apply retention policy to ClickHouse"""
    policy = RETENTION_POLICIES["clickhouse"]
    if not policy["enabled"]:
        print("[ClickHouse] Retention policy disabled, skipping")
        return

    print(f"[ClickHouse] Applying {policy['retention_days']}-day retention to {policy['table']}")
    
    try:
        client = ClickHouseClient(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            user=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD
        )
        
        # Set TTL on table
        ttl_sql = f"""
            ALTER TABLE {policy['table']}
            MODIFY TTL {policy['timestamp_column']} + INTERVAL {policy['retention_days']} DAY
        """
        client.execute(ttl_sql)
        print(f"[ClickHouse] TTL set to {policy['retention_days']} days")
        
        # Get count before cleanup
        count_sql = f"SELECT count() FROM {policy['table']} WHERE {policy['timestamp_column']} < now() - INTERVAL {policy['retention_days']} DAY"
        old_count = client.execute(count_sql)[0][0]
        
        if old_count > 0:
            # Manual cleanup for immediate effect
            delete_sql = f"ALTER TABLE {policy['table']} DELETE WHERE {policy['timestamp_column']} < now() - INTERVAL {policy['retention_days']} DAY"
            client.execute(delete_sql)
            print(f"[ClickHouse] Deleted {old_count} records older than {policy['retention_days']} days")
        else:
            print(f"[ClickHouse] No records to delete")
            
    except Exception as e:
        print(f"[ClickHouse] Error: {e}")


def cleanup_minio(policy_name: str):
    """Apply retention policy to MinIO bucket/prefix"""
    policy = RETENTION_POLICIES[policy_name]
    if not policy["enabled"]:
        print(f"[MinIO/{policy_name}] Retention policy disabled, skipping")
        return

    print(f"[MinIO/{policy_name}] Applying {policy['retention_days']}-day retention to {policy['bucket']}/{policy['prefix']}")
    
    try:
        client = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)
        
        cutoff_date = datetime.utcnow() - timedelta(days=policy['retention_days'])
        objects_to_delete = []
        
        # List objects with prefix
        objects = client.list_objects(policy['bucket'], prefix=policy['prefix'], recursive=True)
        
        for obj in objects:
            if obj.last_modified < cutoff_date:
                objects_to_delete.append(DeleteObject(obj.object_name))
        
        if objects_to_delete:
            # Delete objects
            errors = client.remove_objects(policy['bucket'], objects_to_delete)
            deleted_count = len(objects_to_delete)
            error_count = sum(1 for _ in errors)
            print(f"[MinIO/{policy_name}] Deleted {deleted_count - error_count} objects (errors: {error_count})")
        else:
            print(f"[MinIO/{policy_name}] No objects to delete")
            
    except Exception as e:
        print(f"[MinIO/{policy_name}] Error: {e}")


def cleanup_postgres():
    """Apply retention policy to PostgreSQL"""
    policy = RETENTION_POLICIES["postgres_metadata"]
    if not policy["enabled"]:
        print("[PostgreSQL] Retention policy disabled, skipping")
        return

    print(f"[PostgreSQL] Applying {policy['retention_days']}-day retention to {policy['table']}")
    
    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD
        )
        cur = conn.cursor()
        
        # Get count before cleanup
        count_sql = f"SELECT count(*) FROM {policy['table']} WHERE {policy['timestamp_column']} < NOW() - INTERVAL '{policy['retention_days']} days'"
        cur.execute(count_sql)
        old_count = cur.fetchone()[0]
        
        if old_count > 0:
            delete_sql = get_retention_sql(policy['table'], policy['timestamp_column'], policy['retention_days'])
            cur.execute(delete_sql)
            conn.commit()
            print(f"[PostgreSQL] Deleted {old_count} records older than {policy['retention_days']} days")
        else:
            print(f"[PostgreSQL] No records to delete")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"[PostgreSQL] Error: {e}")


def main():
    print(f"=== Data Retention Cleanup - {datetime.utcnow().isoformat()} ===")
    
    cleanup_clickhouse()
    cleanup_minio("minio_raw")
    cleanup_minio("minio_curated")
    cleanup_postgres()
    
    print("=== Cleanup Complete ===")


if __name__ == "__main__":
    main()
