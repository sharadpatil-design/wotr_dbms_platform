"""
ClickHouse Optimization Module

Implements performance optimizations for ClickHouse:
- Materialized views for common aggregations
- Proper table partitioning
- Index strategies
- Query optimization helpers
"""

import logging
from typing import List, Dict, Any
from clickhouse_driver import Client as ClickHouseClient

logger = logging.getLogger(__name__)


class ClickHouseOptimizer:
    """ClickHouse optimization manager."""
    
    def __init__(self, client: ClickHouseClient):
        """Initialize optimizer with ClickHouse client."""
        self.client = client
        logger.info("ClickHouseOptimizer initialized")
    
    def create_materialized_views(self):
        """Create materialized views for common aggregations."""
        logger.info("Creating materialized views...")
        
        # Hourly event aggregation view
        hourly_agg_mv = """
        CREATE MATERIALIZED VIEW IF NOT EXISTS wotr.events_hourly_mv
        ENGINE = SummingMergeTree()
        PARTITION BY toYYYYMMDD(hour)
        ORDER BY (hour, event_type)
        AS SELECT
            toStartOfHour(created_at) as hour,
            event_type,
            count() as event_count,
            sum(size_bytes) as total_size_bytes,
            avg(size_bytes) as avg_size_bytes
        FROM wotr.ingested_data
        GROUP BY hour, event_type
        """
        
        # Daily event aggregation view
        daily_agg_mv = """
        CREATE MATERIALIZED VIEW IF NOT EXISTS wotr.events_daily_mv
        ENGINE = SummingMergeTree()
        PARTITION BY toYYYYMM(day)
        ORDER BY (day, event_type)
        AS SELECT
            toDate(created_at) as day,
            event_type,
            count() as event_count,
            sum(size_bytes) as total_size_bytes,
            avg(size_bytes) as avg_size_bytes,
            uniq(id) as unique_events
        FROM wotr.ingested_data
        GROUP BY day, event_type
        """
        
        # Source statistics view
        source_stats_mv = """
        CREATE MATERIALIZED VIEW IF NOT EXISTS wotr.source_stats_mv
        ENGINE = SummingMergeTree()
        PARTITION BY toYYYYMMDD(date)
        ORDER BY (date, source)
        AS SELECT
            toDate(created_at) as date,
            source,
            count() as event_count,
            sum(size_bytes) as total_bytes
        FROM wotr.ingested_data
        GROUP BY date, source
        """
        
        # Validation failure tracking
        validation_failures_mv = """
        CREATE MATERIALIZED VIEW IF NOT EXISTS wotr.validation_failures_mv
        ENGINE = MergeTree()
        PARTITION BY toYYYYMMDD(created_at)
        ORDER BY (created_at, event_type)
        AS SELECT
            created_at,
            event_type,
            error_message,
            source,
            payload
        FROM wotr.ingested_data
        WHERE validation_status = 'failed'
        """
        
        views = [
            ("events_hourly_mv", hourly_agg_mv),
            ("events_daily_mv", daily_agg_mv),
            ("source_stats_mv", source_stats_mv),
            ("validation_failures_mv", validation_failures_mv)
        ]
        
        for view_name, view_sql in views:
            try:
                self.client.execute(view_sql)
                logger.info(f"Created/verified materialized view: {view_name}")
            except Exception as e:
                logger.error(f"Failed to create materialized view {view_name}: {e}")
    
    def optimize_tables(self):
        """Optimize tables for better performance."""
        logger.info("Optimizing tables...")
        
        tables = ["ingested_data"]
        
        for table in tables:
            try:
                # Run OPTIMIZE to merge parts
                self.client.execute(f"OPTIMIZE TABLE wotr.{table} FINAL")
                logger.info(f"Optimized table: {table}")
            except Exception as e:
                logger.warning(f"Failed to optimize table {table}: {e}")
    
    def create_indexes(self):
        """Create indexes for common query patterns."""
        logger.info("Creating indexes...")
        
        # Skip index for validation_status
        skip_index_1 = """
        ALTER TABLE wotr.ingested_data
        ADD INDEX IF NOT EXISTS idx_validation_status validation_status TYPE set(10) GRANULARITY 4
        """
        
        # Skip index for event_type
        skip_index_2 = """
        ALTER TABLE wotr.ingested_data
        ADD INDEX IF NOT EXISTS idx_event_type event_type TYPE set(100) GRANULARITY 4
        """
        
        # Bloom filter for source field
        bloom_filter = """
        ALTER TABLE wotr.ingested_data
        ADD INDEX IF NOT EXISTS idx_source_bloom source TYPE bloom_filter() GRANULARITY 1
        """
        
        indexes = [
            ("idx_validation_status", skip_index_1),
            ("idx_event_type", skip_index_2),
            ("idx_source_bloom", bloom_filter)
        ]
        
        for index_name, index_sql in indexes:
            try:
                self.client.execute(index_sql)
                logger.info(f"Created/verified index: {index_name}")
            except Exception as e:
                logger.warning(f"Failed to create index {index_name}: {e}")
    
    def update_table_settings(self):
        """Update table settings for better performance."""
        logger.info("Updating table settings...")
        
        # Increase merge threads for faster merges
        settings = [
            "ALTER TABLE wotr.ingested_data MODIFY SETTING max_concurrent_queries = 100",
            "ALTER TABLE wotr.ingested_data MODIFY SETTING merge_with_ttl_timeout = 3600"
        ]
        
        for setting in settings:
            try:
                self.client.execute(setting)
                logger.info(f"Applied setting: {setting}")
            except Exception as e:
                logger.warning(f"Failed to apply setting: {e}")
    
    def get_table_statistics(self) -> List[Dict[str, Any]]:
        """Get table statistics for monitoring."""
        query = """
        SELECT
            database,
            table,
            sum(rows) as total_rows,
            sum(bytes_on_disk) as bytes_on_disk,
            sum(data_compressed_bytes) as compressed_bytes,
            sum(data_uncompressed_bytes) as uncompressed_bytes,
            count() as parts_count
        FROM system.parts
        WHERE database = 'wotr' AND active = 1
        GROUP BY database, table
        ORDER BY total_rows DESC
        """
        
        try:
            result = self.client.execute(query)
            stats = []
            for row in result:
                stats.append({
                    "database": row[0],
                    "table": row[1],
                    "total_rows": row[2],
                    "bytes_on_disk": row[3],
                    "compressed_bytes": row[4],
                    "uncompressed_bytes": row[5],
                    "parts_count": row[6],
                    "compression_ratio": round(row[5] / row[4], 2) if row[4] > 0 else 0
                })
            return stats
        except Exception as e:
            logger.error(f"Failed to get table statistics: {e}")
            return []
    
    def get_query_performance_stats(self) -> List[Dict[str, Any]]:
        """Get slow query statistics."""
        query = """
        SELECT
            query_id,
            substring(query, 1, 100) as query_preview,
            type,
            query_duration_ms,
            read_rows,
            read_bytes,
            written_rows,
            written_bytes,
            memory_usage
        FROM system.query_log
        WHERE type = 'QueryFinish'
          AND event_time > now() - INTERVAL 1 HOUR
          AND query_duration_ms > 1000
        ORDER BY query_duration_ms DESC
        LIMIT 20
        """
        
        try:
            result = self.client.execute(query)
            stats = []
            for row in result:
                stats.append({
                    "query_id": row[0],
                    "query_preview": row[1],
                    "type": row[2],
                    "duration_ms": row[3],
                    "read_rows": row[4],
                    "read_bytes": row[5],
                    "written_rows": row[6],
                    "written_bytes": row[7],
                    "memory_usage": row[8]
                })
            return stats
        except Exception as e:
            logger.error(f"Failed to get query performance stats: {e}")
            return []
    
    def vacuum_old_partitions(self, days_to_keep: int = 90):
        """Drop old partitions to free up space."""
        logger.info(f"Checking for partitions older than {days_to_keep} days...")
        
        # Get old partitions
        partition_query = """
        SELECT DISTINCT partition
        FROM system.parts
        WHERE database = 'wotr'
          AND table = 'ingested_data'
          AND toDate(partition) < today() - INTERVAL {days} DAY
        ORDER BY partition
        """.format(days=days_to_keep)
        
        try:
            old_partitions = self.client.execute(partition_query)
            
            for partition in old_partitions:
                partition_id = partition[0]
                try:
                    drop_sql = f"ALTER TABLE wotr.ingested_data DROP PARTITION '{partition_id}'"
                    self.client.execute(drop_sql)
                    logger.info(f"Dropped old partition: {partition_id}")
                except Exception as e:
                    logger.error(f"Failed to drop partition {partition_id}: {e}")
        except Exception as e:
            logger.error(f"Failed to query old partitions: {e}")
    
    def analyze_query(self, query: str) -> Dict[str, Any]:
        """Analyze query execution plan."""
        explain_query = f"EXPLAIN {query}"
        
        try:
            result = self.client.execute(explain_query)
            return {
                "query": query,
                "plan": [row[0] for row in result]
            }
        except Exception as e:
            logger.error(f"Failed to analyze query: {e}")
            return {"error": str(e)}


# ===== Query Optimization Helpers =====

class QueryOptimizer:
    """Helper class for optimizing ClickHouse queries."""
    
    @staticmethod
    def add_prewhere(query: str, filter_column: str) -> str:
        """
        Add PREWHERE clause for better performance.
        PREWHERE filters rows before reading all columns.
        """
        # Simple implementation - in production, parse SQL properly
        if "WHERE" in query and "PREWHERE" not in query:
            return query.replace("WHERE", f"PREWHERE {filter_column} AND WHERE", 1)
        return query
    
    @staticmethod
    def add_limit(query: str, limit: int = 10000) -> str:
        """Add LIMIT to unbounded queries."""
        if "LIMIT" not in query.upper():
            return f"{query.rstrip(';')} LIMIT {limit}"
        return query
    
    @staticmethod
    def optimize_group_by(query: str) -> str:
        """
        Optimize GROUP BY queries.
        Use low cardinality for high-cardinality columns.
        """
        # This is a placeholder - actual implementation would be more sophisticated
        return query
    
    @staticmethod
    def recommend_partition_key(table_stats: Dict[str, Any]) -> str:
        """Recommend partition key based on table statistics."""
        # Analyze data distribution and recommend partitioning
        # For time-series data, typically partition by date
        return "toYYYYMM(created_at)"
    
    @staticmethod
    def estimate_query_cost(query: str, client: ClickHouseClient) -> Dict[str, Any]:
        """Estimate query resource consumption."""
        try:
            # Use EXPLAIN ESTIMATE for cost estimation
            explain_query = f"EXPLAIN ESTIMATE {query}"
            result = client.execute(explain_query)
            
            return {
                "estimated_rows": result[0][0] if result else 0,
                "estimated_bytes": result[0][1] if len(result[0]) > 1 else 0
            }
        except Exception as e:
            logger.error(f"Failed to estimate query cost: {e}")
            return {}


# ===== Initialization Function =====

def initialize_clickhouse_optimizations(client: ClickHouseClient):
    """Initialize all ClickHouse optimizations."""
    logger.info("Initializing ClickHouse optimizations...")
    
    optimizer = ClickHouseOptimizer(client)
    
    # Create materialized views
    optimizer.create_materialized_views()
    
    # Create indexes
    optimizer.create_indexes()
    
    # Update settings
    optimizer.update_table_settings()
    
    # Get initial statistics
    stats = optimizer.get_table_statistics()
    logger.info(f"ClickHouse table statistics: {stats}")
    
    logger.info("ClickHouse optimizations initialized")


# ===== Optimized Query Templates =====

OPTIMIZED_QUERIES = {
    "event_stats_hourly": """
        SELECT hour, event_type, sum(event_count) as total_events
        FROM wotr.events_hourly_mv
        WHERE hour >= toStartOfHour(now()) - INTERVAL 24 HOUR
        GROUP BY hour, event_type
        ORDER BY hour DESC, total_events DESC
    """,
    
    "event_stats_daily": """
        SELECT day, event_type, sum(event_count) as total_events
        FROM wotr.events_daily_mv
        WHERE day >= today() - INTERVAL 30 DAY
        GROUP BY day, event_type
        ORDER BY day DESC, total_events DESC
    """,
    
    "top_sources": """
        SELECT source, sum(event_count) as total_events
        FROM wotr.source_stats_mv
        WHERE date >= today() - INTERVAL 7 DAY
        GROUP BY source
        ORDER BY total_events DESC
        LIMIT 100
    """,
    
    "recent_failures": """
        SELECT created_at, event_type, error_message
        FROM wotr.validation_failures_mv
        WHERE created_at >= now() - INTERVAL 1 HOUR
        ORDER BY created_at DESC
        LIMIT 100
    """,
    
    "event_distribution": """
        SELECT 
            event_type,
            count() as cnt,
            avg(size_bytes) as avg_size,
            max(created_at) as last_event
        FROM wotr.ingested_data
        PREWHERE created_at > now() - INTERVAL 24 HOUR
        WHERE validation_status = 'success'
        GROUP BY event_type
        ORDER BY cnt DESC
    """
}


def get_optimized_query(query_name: str) -> str:
    """Get pre-optimized query by name."""
    return OPTIMIZED_QUERIES.get(query_name, "")
