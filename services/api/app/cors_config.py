"""
CORS (Cross-Origin Resource Sharing) configuration
"""
import os
from typing import List


def get_cors_origins() -> List[str]:
    """Get allowed CORS origins from environment"""
    origins_str = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8080")
    
    # Parse comma-separated origins
    origins = [origin.strip() for origin in origins_str.split(",") if origin.strip()]
    
    # Add wildcard for development if configured
    if os.getenv("CORS_ALLOW_ALL", "false").lower() == "true":
        origins = ["*"]
    
    return origins


# CORS configuration
CORS_CONFIG = {
    "allow_origins": get_cors_origins(),
    "allow_credentials": os.getenv("CORS_ALLOW_CREDENTIALS", "true").lower() == "true",
    "allow_methods": os.getenv("CORS_ALLOW_METHODS", "GET,POST,PUT,DELETE,OPTIONS").split(","),
    "allow_headers": os.getenv("CORS_ALLOW_HEADERS", "Content-Type,Authorization,X-API-Key").split(","),
    "expose_headers": os.getenv("CORS_EXPOSE_HEADERS", "X-Request-ID,X-RateLimit-Limit,X-RateLimit-Remaining").split(","),
    "max_age": int(os.getenv("CORS_MAX_AGE", "600")),  # 10 minutes
}
