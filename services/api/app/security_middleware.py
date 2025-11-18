"""
Security middleware for additional protections
"""
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
import time
from typing import Dict
import hashlib


class SecurityHeadersMiddleware:
    """Add security headers to all responses"""
    
    async def __call__(self, request: Request, call_next):
        response = await call_next(request)
        
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        
        # Remove server header
        if "server" in response.headers:
            del response.headers["server"]
        
        return response


class RequestIDMiddleware:
    """Add unique request ID to each request for tracking"""
    
    async def __call__(self, request: Request, call_next):
        # Generate request ID
        request_id = hashlib.sha256(
            f"{time.time()}{request.client.host}".encode()
        ).hexdigest()[:16]
        
        # Add to request state
        request.state.request_id = request_id
        
        # Process request
        response = await call_next(request)
        
        # Add to response headers
        response.headers["X-Request-ID"] = request_id
        
        return response


# IP whitelist for administrative endpoints
ADMIN_IP_WHITELIST = set([
    "127.0.0.1",
    "::1",
    # Add more IPs as needed
])


def check_ip_whitelist(request: Request, whitelist: set = ADMIN_IP_WHITELIST):
    """Check if request IP is in whitelist"""
    client_ip = request.client.host
    
    # Check X-Forwarded-For header (if behind proxy)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    
    if client_ip not in whitelist:
        raise HTTPException(
            status_code=403,
            detail="Access denied: IP not whitelisted"
        )
    
    return True
