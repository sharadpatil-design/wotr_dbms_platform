"""
Rate limiting configuration and middleware
Uses slowapi for rate limiting based on IP address or API key
"""
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request
import os


def get_identifier(request: Request) -> str:
    """
    Get identifier for rate limiting.
    Uses API key if present, otherwise falls back to IP address.
    """
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"apikey:{api_key}"
    return f"ip:{get_remote_address(request)}"


# Rate limiter instance
limiter = Limiter(
    key_func=get_identifier,
    default_limits=[os.getenv("RATE_LIMIT_DEFAULT", "100/minute")],
    storage_uri=os.getenv("RATE_LIMIT_STORAGE", "memory://"),
    strategy="fixed-window"
)


# Rate limit configurations for different endpoints
RATE_LIMITS = {
    "health": os.getenv("RATE_LIMIT_HEALTH", "30/minute"),
    "metrics": os.getenv("RATE_LIMIT_METRICS", "60/minute"),
    "ingest": os.getenv("RATE_LIMIT_INGEST", "100/minute"),
    "retention": os.getenv("RATE_LIMIT_RETENTION", "10/minute"),
}
