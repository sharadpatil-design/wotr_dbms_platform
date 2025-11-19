"""
Connection Pool Management for WOTR Platform

Implements connection pooling for:
- PostgreSQL (psycopg2 pool)
- ClickHouse (connection pool)
- Kafka (producer pool)
- Redis (connection pool)

Benefits:
- Reduced connection overhead
- Better resource utilization
- Improved performance under load
- Automatic connection recycling
"""

import os
import json
import logging
from typing import Optional
from contextlib import contextmanager
import psycopg2
from psycopg2 import pool
from clickhouse_driver import Client as ClickHouseClient
from kafka import KafkaProducer
import redis
from prometheus_client import Gauge, Counter

logger = logging.getLogger(__name__)

# Metrics for connection pools
pg_pool_size = Gauge("postgres_pool_size", "Current PostgreSQL connection pool size")
pg_pool_available = Gauge("postgres_pool_available", "Available PostgreSQL connections")
clickhouse_pool_size = Gauge("clickhouse_pool_size", "Current ClickHouse connection pool size")
redis_pool_size = Gauge("redis_pool_size", "Current Redis connection pool size")
pool_checkout_failures = Counter("pool_checkout_failures_total", "Failed connection checkouts", ["pool"])


# ===== PostgreSQL Connection Pool =====

class PostgreSQLPool:
    """PostgreSQL connection pool manager."""
    
    def __init__(
        self,
        minconn: int = 2,
        maxconn: int = 10,
        host: str = "postgres",
        port: int = 5432,
        user: str = "postgres",
        password: str = "postgres",
        database: str = "wotr"
    ):
        """Initialize PostgreSQL connection pool."""
        self.pool = None
        self.minconn = minconn
        self.maxconn = maxconn
        self.config = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": database
        }
        logger.info(f"Initializing PostgreSQL pool: min={minconn}, max={maxconn}")
    
    def initialize(self):
        """Create the connection pool."""
        try:
            self.pool = pool.ThreadedConnectionPool(
                self.minconn,
                self.maxconn,
                **self.config
            )
            pg_pool_size.set(self.maxconn)
            logger.info("PostgreSQL connection pool initialized")
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL pool: {e}")
            raise
    
    @contextmanager
    def get_connection(self):
        """Get a connection from the pool (context manager)."""
        conn = None
        try:
            conn = self.pool.getconn()
            pg_pool_available.dec()
            yield conn
        except pool.PoolError as e:
            pool_checkout_failures.labels(pool="postgres").inc()
            logger.error(f"Failed to get PostgreSQL connection: {e}")
            raise
        finally:
            if conn:
                self.pool.putconn(conn)
                pg_pool_available.inc()
    
    def close_all(self):
        """Close all connections in the pool."""
        if self.pool:
            self.pool.closeall()
            logger.info("PostgreSQL connection pool closed")


# ===== ClickHouse Connection Pool =====

class ClickHousePool:
    """ClickHouse connection pool manager."""
    
    def __init__(
        self,
        max_connections: int = 10,
        host: str = "clickhouse",
        port: int = 9000,
        database: str = "wotr",
        user: str = "default",
        password: str = ""
    ):
        """Initialize ClickHouse connection pool."""
        self.connections = []
        self.max_connections = max_connections
        self.current_index = 0
        self.config = {
            "host": host,
            "port": port,
            "database": database,
            "user": user,
            "password": password,
            "settings": {
                "max_execution_time": 60,
                "max_memory_usage": 10_000_000_000  # 10GB
            }
        }
        logger.info(f"Initializing ClickHouse pool: max={max_connections}")
    
    def initialize(self):
        """Create connection pool."""
        try:
            for i in range(self.max_connections):
                client = ClickHouseClient(**self.config)
                self.connections.append(client)
            clickhouse_pool_size.set(self.max_connections)
            logger.info(f"ClickHouse connection pool initialized with {self.max_connections} connections")
        except Exception as e:
            logger.error(f"Failed to initialize ClickHouse pool: {e}")
            raise
    
    def get_client(self) -> ClickHouseClient:
        """Get a ClickHouse client (round-robin)."""
        if not self.connections:
            pool_checkout_failures.labels(pool="clickhouse").inc()
            raise RuntimeError("ClickHouse connection pool not initialized")
        
        # Round-robin connection selection
        client = self.connections[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.connections)
        return client
    
    def close_all(self):
        """Close all connections."""
        for client in self.connections:
            try:
                client.disconnect()
            except Exception as e:
                logger.warning(f"Error closing ClickHouse connection: {e}")
        self.connections = []
        logger.info("ClickHouse connection pool closed")


# ===== Kafka Producer Pool =====

class KafkaProducerPool:
    """Kafka producer pool manager."""
    
    def __init__(
        self,
        pool_size: int = 5,
        bootstrap_servers: str = "redpanda:9092"
    ):
        """Initialize Kafka producer pool."""
        self.producers = []
        self.pool_size = pool_size
        self.bootstrap_servers = bootstrap_servers
        self.current_index = 0
        logger.info(f"Initializing Kafka producer pool: size={pool_size}")
    
    def initialize(self):
        """Create producer pool."""
        try:
            for i in range(self.pool_size):
                producer = KafkaProducer(
                    bootstrap_servers=self.bootstrap_servers,
                    value_serializer=lambda v: v if isinstance(v, bytes) else json.dumps(v).encode('utf-8'),
                    acks='all',
                    retries=3,
                    max_in_flight_requests_per_connection=5,
                    compression_type='gzip'
                )
                self.producers.append(producer)
            logger.info(f"Kafka producer pool initialized with {self.pool_size} producers")
        except Exception as e:
            logger.error(f"Failed to initialize Kafka producer pool: {e}")
            raise
    
    def get_producer(self) -> KafkaProducer:
        """Get a Kafka producer (round-robin)."""
        if not self.producers:
            pool_checkout_failures.labels(pool="kafka").inc()
            raise RuntimeError("Kafka producer pool not initialized")
        
        producer = self.producers[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.producers)
        return producer
    
    def close_all(self):
        """Close all producers."""
        for producer in self.producers:
            try:
                producer.flush()
                producer.close()
            except Exception as e:
                logger.warning(f"Error closing Kafka producer: {e}")
        self.producers = []
        logger.info("Kafka producer pool closed")


# ===== Redis Connection Pool =====

class RedisPool:
    """Redis connection pool manager."""
    
    def __init__(
        self,
        host: str = "redis",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        max_connections: int = 50,
        decode_responses: bool = True
    ):
        """Initialize Redis connection pool."""
        self.pool = redis.ConnectionPool(
            host=host,
            port=port,
            db=db,
            password=password,
            max_connections=max_connections,
            decode_responses=decode_responses,
            socket_keepalive=True,
            socket_timeout=5,
            socket_connect_timeout=5
        )
        redis_pool_size.set(max_connections)
        logger.info(f"Redis connection pool initialized: max={max_connections}")
    
    def get_client(self) -> redis.Redis:
        """Get a Redis client from the pool."""
        try:
            return redis.Redis(connection_pool=self.pool)
        except Exception as e:
            pool_checkout_failures.labels(pool="redis").inc()
            logger.error(f"Failed to get Redis connection: {e}")
            raise
    
    def close(self):
        """Close the connection pool."""
        self.pool.disconnect()
        logger.info("Redis connection pool closed")


# ===== Global Pool Instances =====

# These will be initialized at startup
pg_pool: Optional[PostgreSQLPool] = None
clickhouse_pool: Optional[ClickHousePool] = None
kafka_producer_pool: Optional[KafkaProducerPool] = None
redis_pool: Optional[RedisPool] = None


def initialize_pools():
    """Initialize all connection pools."""
    global pg_pool, clickhouse_pool, kafka_producer_pool, redis_pool
    
    logger.info("Initializing connection pools...")
    
    # PostgreSQL pool
    pg_pool = PostgreSQLPool(
        minconn=int(os.getenv("POSTGRES_POOL_MIN", 2)),
        maxconn=int(os.getenv("POSTGRES_POOL_MAX", 10)),
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", 5432)),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
        database=os.getenv("POSTGRES_DB", "wotr")
    )
    pg_pool.initialize()
    
    # ClickHouse pool
    clickhouse_pool = ClickHousePool(
        max_connections=int(os.getenv("CLICKHOUSE_POOL_SIZE", 10)),
        host=os.getenv("CLICKHOUSE_HOST", "clickhouse"),
        port=int(os.getenv("CLICKHOUSE_PORT", 9000)),
        database=os.getenv("CLICKHOUSE_DB", "wotr"),
        user=os.getenv("CLICKHOUSE_USER", "default"),
        password=os.getenv("CLICKHOUSE_PASSWORD", "")
    )
    clickhouse_pool.initialize()
    
    # Kafka producer pool
    kafka_producer_pool = KafkaProducerPool(
        pool_size=int(os.getenv("KAFKA_PRODUCER_POOL_SIZE", 5)),
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP", "redpanda:9092")
    )
    kafka_producer_pool.initialize()
    
    # Redis pool
    redis_pool = RedisPool(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        db=int(os.getenv("REDIS_DB", 0)),
        password=os.getenv("REDIS_PASSWORD"),
        max_connections=int(os.getenv("REDIS_POOL_SIZE", 50))
    )
    
    logger.info("All connection pools initialized successfully")


def close_all_pools():
    """Close all connection pools."""
    logger.info("Closing all connection pools...")
    
    if pg_pool:
        pg_pool.close_all()
    if clickhouse_pool:
        clickhouse_pool.close_all()
    if kafka_producer_pool:
        kafka_producer_pool.close_all()
    if redis_pool:
        redis_pool.close()
    
    logger.info("All connection pools closed")


# ===== Helper Functions =====

def get_pg_connection():
    """Get a PostgreSQL connection from the pool."""
    if not pg_pool:
        raise RuntimeError("PostgreSQL pool not initialized")
    return pg_pool.get_connection()


def get_clickhouse_client() -> ClickHouseClient:
    """Get a ClickHouse client from the pool."""
    if not clickhouse_pool:
        raise RuntimeError("ClickHouse pool not initialized")
    return clickhouse_pool.get_client()


def get_kafka_producer() -> KafkaProducer:
    """Get a Kafka producer from the pool."""
    if not kafka_producer_pool:
        raise RuntimeError("Kafka producer pool not initialized")
    return kafka_producer_pool.get_producer()


def get_redis_client() -> redis.Redis:
    """Get a Redis client from the pool."""
    if not redis_pool:
        raise RuntimeError("Redis pool not initialized")
    return redis_pool.get_client()
