"""
Authentication utilities for FastAPI
Provides API key-based authentication
"""
import os
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from typing import Optional

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

# Load API keys from environment (comma-separated)
VALID_API_KEYS = set(os.getenv("API_KEYS", "").split(","))

# Add default dev key if no keys configured
if not VALID_API_KEYS or VALID_API_KEYS == {''}:
    VALID_API_KEYS = {"dev-key-12345"}
    print("[WARNING] Using default API key. Set API_KEYS environment variable for production!")


async def get_api_key(api_key_header: str = Security(api_key_header)) -> str:
    """
    Validate API key from request header.
    Raises HTTPException if invalid or missing.
    """
    if api_key_header and api_key_header in VALID_API_KEYS:
        return api_key_header
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )


def is_authenticated(api_key: Optional[str] = None) -> bool:
    """
    Check if provided API key is valid.
    Used for optional authentication checks.
    """
    return api_key in VALID_API_KEYS if api_key else False
