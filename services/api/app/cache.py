"""
Redis Caching Layer for WOTR Platform

Implements caching strategies for:
- Query results (ClickHouse queries)
- API responses
- Session data
- Event statistics
- Service health status

Features:
- TTL-based expiration
- Cache invalidation
- Batch operations
- Metrics tracking
"""

import json
import hashlib
import logging
from typing import Any, Optional, List, Dict, Callable
from functools import wraps
from datetime import timedelta
import redis
from prometheus_client import Counter, Histogram

logger = logging.getLogger(__name__)

# Metrics
cache_hits = Counter("cache_hits_total", "Cache hits", ["cache_type"])
cache_misses = Counter("cache_misses_total", "Cache misses", ["cache_type"])
cache_errors = Counter("cache_errors_total", "Cache operation errors", ["operation"])
cache_latency = Histogram("cache_operation_latency_seconds", "Cache operation latency", ["operation"])


class CacheManager:
    """Redis cache manager with TTL and invalidation support."""
    
    # Default TTLs (seconds)
    TTL_SHORT = 60  # 1 minute
    TTL_MEDIUM = 300  # 5 minutes
    TTL_LONG = 3600  # 1 hour
    TTL_VERY_LONG = 86400  # 24 hours
    
    def __init__(self, redis_client: redis.Redis):
        """Initialize cache manager."""
        self.redis = redis_client
        self.prefix = "wotr:"
        logger.info("CacheManager initialized")
    
    def _make_key(self, cache_type: str, key: str) -> str:
        """Create namespaced cache key."""
        return f"{self.prefix}{cache_type}:{key}"
    
    def get(self, cache_type: str, key: str) -> Optional[Any]:
        """Get value from cache."""
        cache_key = self._make_key(cache_type, key)
        
        try:
            with cache_latency.labels(operation="get").time():
                value = self.redis.get(cache_key)
            
            if value:
                cache_hits.labels(cache_type=cache_type).inc()
                logger.debug(f"Cache hit: {cache_key}")
                return json.loads(value)
            else:
                cache_misses.labels(cache_type=cache_type).inc()
                logger.debug(f"Cache miss: {cache_key}")
                return None
        except Exception as e:
            cache_errors.labels(operation="get").inc()
            logger.error(f"Cache get error for {cache_key}: {e}")
            return None
    
    def set(self, cache_type: str, key: str, value: Any, ttl: int = TTL_MEDIUM) -> bool:
        """Set value in cache with TTL."""
        cache_key = self._make_key(cache_type, key)
        
        try:
            with cache_latency.labels(operation="set").time():
                serialized = json.dumps(value)
                self.redis.setex(cache_key, ttl, serialized)
            
            logger.debug(f"Cache set: {cache_key} (TTL: {ttl}s)")
            return True
        except Exception as e:
            cache_errors.labels(operation="set").inc()
            logger.error(f"Cache set error for {cache_key}: {e}")
            return False
    
    def delete(self, cache_type: str, key: str) -> bool:
        """Delete value from cache."""
        cache_key = self._make_key(cache_type, key)
        
        try:
            with cache_latency.labels(operation="delete").time():
                self.redis.delete(cache_key)
            
            logger.debug(f"Cache delete: {cache_key}")
            return True
        except Exception as e:
            cache_errors.labels(operation="delete").inc()
            logger.error(f"Cache delete error for {cache_key}: {e}")
            return False
    
    def delete_pattern(self, cache_type: str, pattern: str) -> int:
        """Delete all keys matching pattern."""
        try:
            cache_pattern = self._make_key(cache_type, pattern)
            keys = self.redis.keys(cache_pattern)
            
            if keys:
                with cache_latency.labels(operation="delete_pattern").time():
                    deleted = self.redis.delete(*keys)
                logger.info(f"Deleted {deleted} keys matching {cache_pattern}")
                return deleted
            return 0
        except Exception as e:
            cache_errors.labels(operation="delete_pattern").inc()
            logger.error(f"Cache delete_pattern error: {e}")
            return 0
    
    def exists(self, cache_type: str, key: str) -> bool:
        """Check if key exists in cache."""
        cache_key = self._make_key(cache_type, key)
        try:
            return self.redis.exists(cache_key) > 0
        except Exception as e:
            cache_errors.labels(operation="exists").inc()
            logger.error(f"Cache exists error for {cache_key}: {e}")
            return False
    
    def increment(self, cache_type: str, key: str, amount: int = 1) -> Optional[int]:
        """Increment counter."""
        cache_key = self._make_key(cache_type, key)
        try:
            with cache_latency.labels(operation="increment").time():
                return self.redis.incrby(cache_key, amount)
        except Exception as e:
            cache_errors.labels(operation="increment").inc()
            logger.error(f"Cache increment error for {cache_key}: {e}")
            return None
    
    def set_multiple(self, cache_type: str, mapping: Dict[str, Any], ttl: int = TTL_MEDIUM) -> bool:
        """Set multiple key-value pairs."""
        try:
            pipeline = self.redis.pipeline()
            for key, value in mapping.items():
                cache_key = self._make_key(cache_type, key)
                serialized = json.dumps(value)
                pipeline.setex(cache_key, ttl, serialized)
            
            with cache_latency.labels(operation="set_multiple").time():
                pipeline.execute()
            
            logger.debug(f"Cache set_multiple: {len(mapping)} keys")
            return True
        except Exception as e:
            cache_errors.labels(operation="set_multiple").inc()
            logger.error(f"Cache set_multiple error: {e}")
            return False
    
    def get_multiple(self, cache_type: str, keys: List[str]) -> Dict[str, Any]:
        """Get multiple values."""
        try:
            cache_keys = [self._make_key(cache_type, k) for k in keys]
            
            with cache_latency.labels(operation="get_multiple").time():
                values = self.redis.mget(cache_keys)
            
            result = {}
            for i, key in enumerate(keys):
                if values[i]:
                    cache_hits.labels(cache_type=cache_type).inc()
                    result[key] = json.loads(values[i])
                else:
                    cache_misses.labels(cache_type=cache_type).inc()
            
            logger.debug(f"Cache get_multiple: {len(result)}/{len(keys)} found")
            return result
        except Exception as e:
            cache_errors.labels(operation="get_multiple").inc()
            logger.error(f"Cache get_multiple error: {e}")
            return {}
    
    def flush_cache_type(self, cache_type: str) -> int:
        """Flush all keys of a specific cache type."""
        return self.delete_pattern(cache_type, "*")


# ===== Cache Decorators =====

def cache_result(cache_type: str, ttl: int = CacheManager.TTL_MEDIUM, key_prefix: str = ""):
    """
    Decorator to cache function results.
    
    Usage:
        @cache_result("query", ttl=300, key_prefix="events")
        def get_event_stats():
            # expensive query
            return results
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Import here to avoid circular dependency
            from connection_pool import get_redis_client
            
            try:
                redis_client = get_redis_client()
                cache_manager = CacheManager(redis_client)
                
                # Create cache key from function name and arguments
                cache_key_parts = [key_prefix, func.__name__]
                if args:
                    cache_key_parts.append(hashlib.md5(str(args).encode()).hexdigest()[:8])
                if kwargs:
                    cache_key_parts.append(hashlib.md5(str(kwargs).encode()).hexdigest()[:8])
                cache_key = "_".join(filter(None, cache_key_parts))
                
                # Try to get from cache
                cached_value = cache_manager.get(cache_type, cache_key)
                if cached_value is not None:
                    logger.debug(f"Using cached result for {func.__name__}")
                    return cached_value
                
                # Execute function and cache result
                result = func(*args, **kwargs)
                cache_manager.set(cache_type, cache_key, result, ttl)
                
                return result
            except Exception as e:
                logger.warning(f"Cache decorator error for {func.__name__}: {e}")
                # Fall back to executing function without caching
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


# ===== Specialized Cache Functions =====

class QueryCache:
    """Cache for ClickHouse query results."""
    
    CACHE_TYPE = "query"
    
    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager
    
    def get_query_result(self, query: str, params: Optional[Dict] = None) -> Optional[Any]:
        """Get cached query result."""
        cache_key = self._make_query_key(query, params)
        return self.cache.get(self.CACHE_TYPE, cache_key)
    
    def set_query_result(self, query: str, result: Any, params: Optional[Dict] = None, ttl: int = 300):
        """Cache query result."""
        cache_key = self._make_query_key(query, params)
        self.cache.set(self.CACHE_TYPE, cache_key, result, ttl)
    
    def _make_query_key(self, query: str, params: Optional[Dict]) -> str:
        """Create cache key for query."""
        key_data = query
        if params:
            key_data += json.dumps(params, sort_keys=True)
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def invalidate_all(self):
        """Invalidate all query caches."""
        return self.cache.flush_cache_type(self.CACHE_TYPE)


class StatsCache:
    """Cache for statistics and aggregations."""
    
    CACHE_TYPE = "stats"
    
    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager
    
    def get_event_stats(self) -> Optional[Dict]:
        """Get cached event statistics."""
        return self.cache.get(self.CACHE_TYPE, "event_stats")
    
    def set_event_stats(self, stats: Dict, ttl: int = 60):
        """Cache event statistics."""
        self.cache.set(self.CACHE_TYPE, "event_stats", stats, ttl)
    
    def get_system_stats(self) -> Optional[Dict]:
        """Get cached system statistics."""
        return self.cache.get(self.CACHE_TYPE, "system_stats")
    
    def set_system_stats(self, stats: Dict, ttl: int = 30):
        """Cache system statistics."""
        self.cache.set(self.CACHE_TYPE, "system_stats", stats, ttl)
    
    def get_service_health(self) -> Optional[List[Dict]]:
        """Get cached service health."""
        return self.cache.get(self.CACHE_TYPE, "service_health")
    
    def set_service_health(self, health: List[Dict], ttl: int = 10):
        """Cache service health."""
        self.cache.set(self.CACHE_TYPE, "service_health", health, ttl)


class SessionCache:
    """Cache for session data."""
    
    CACHE_TYPE = "session"
    
    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        """Get session data."""
        return self.cache.get(self.CACHE_TYPE, session_id)
    
    def set_session(self, session_id: str, data: Dict, ttl: int = 3600):
        """Set session data."""
        self.cache.set(self.CACHE_TYPE, session_id, data, ttl)
    
    def delete_session(self, session_id: str):
        """Delete session."""
        self.cache.delete(self.CACHE_TYPE, session_id)


# ===== Cache Warming Functions =====

def warm_stats_cache(cache_manager: CacheManager):
    """Pre-warm statistics cache on startup."""
    logger.info("Warming stats cache...")
    
    try:
        from connection_pool import get_clickhouse_client
        
        stats_cache = StatsCache(cache_manager)
        client = get_clickhouse_client()
        
        # Warm event stats
        event_stats_query = """
        SELECT 
            event_type,
            count() as count,
            avg(size_bytes) as avg_size
        FROM wotr.ingested_data
        WHERE created_at > now() - INTERVAL 24 HOUR
        GROUP BY event_type
        """
        
        result = client.execute(event_stats_query)
        stats = [
            {"event_type": row[0], "count": row[1], "avg_size": row[2]}
            for row in result
        ]
        stats_cache.set_event_stats(stats, ttl=300)
        
        logger.info(f"Stats cache warmed with {len(stats)} event types")
    except Exception as e:
        logger.error(f"Failed to warm stats cache: {e}")


# ===== Cache Invalidation Strategies =====

def invalidate_on_write(cache_manager: CacheManager, event_type: str):
    """Invalidate relevant caches when data is written."""
    # Invalidate query caches related to this event type
    query_cache = QueryCache(cache_manager)
    
    # Invalidate stats cache
    stats_cache = StatsCache(cache_manager)
    cache_manager.delete("stats", "event_stats")
    cache_manager.delete("stats", "system_stats")
    
    logger.debug(f"Invalidated caches for event_type: {event_type}")


def scheduled_cache_refresh(cache_manager: CacheManager):
    """Refresh caches on a schedule (call from background task)."""
    logger.info("Scheduled cache refresh triggered")
    
    # Refresh stats cache
    warm_stats_cache(cache_manager)
    
    # Clear old query caches (optional - relies on TTL)
    # query_cache = QueryCache(cache_manager)
    # query_cache.invalidate_all()
