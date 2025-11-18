# Security Hardening - November 18, 2025

## Overview
Comprehensive security hardening including rate limiting, CORS configuration, TLS/SSL setup, and secrets management.

## 1. Rate Limiting

### Implementation
- **Library**: slowapi (compatible with FastAPI)
- **Strategy**: Fixed-window rate limiting
- **Identifier**: API key (if present) or IP address
- **Storage**: In-memory (default) or Redis for distributed systems

### Rate Limits (Configurable)

| Endpoint | Default Limit | Environment Variable |
|----------|--------------|---------------------|
| /health | 30/minute | `RATE_LIMIT_HEALTH` |
| /metrics | 60/minute | `RATE_LIMIT_METRICS` |
| /ingest | 100/minute | `RATE_LIMIT_INGEST` |
| /retention-policies | 10/minute | `RATE_LIMIT_RETENTION` |
| Global default | 100/minute | `RATE_LIMIT_DEFAULT` |

### Configuration

```bash
# Environment variables
RATE_LIMIT_DEFAULT="100/minute"
RATE_LIMIT_INGEST="200/minute"
RATE_LIMIT_STORAGE="redis://localhost:6379"  # For distributed rate limiting
```

### Response Headers

Rate limit headers included in responses:
- `X-RateLimit-Limit`: Maximum requests allowed
- `X-RateLimit-Remaining`: Requests remaining in window
- `X-RateLimit-Reset`: Time when limit resets

### HTTP 429 Response

When rate limit exceeded:
```json
{
  "error": "Rate limit exceeded",
  "message": "100 per 1 minute"
}
```

## 2. CORS Configuration

### Implementation
- **Middleware**: FastAPI CORSMiddleware
- **Configurable Origins**: Via environment variables
- **Credentials Support**: Enabled by default

### Configuration

```bash
# Allow specific origins (comma-separated)
CORS_ORIGINS="http://localhost:3000,https://app.example.com"

# Allow all origins (development only!)
CORS_ALLOW_ALL="true"

# Methods and headers
CORS_ALLOW_METHODS="GET,POST,PUT,DELETE,OPTIONS"
CORS_ALLOW_HEADERS="Content-Type,Authorization,X-API-Key"
CORS_EXPOSE_HEADERS="X-Request-ID,X-RateLimit-Limit,X-RateLimit-Remaining"
CORS_MAX_AGE="600"  # 10 minutes
```

### Preflight Requests

CORS middleware automatically handles OPTIONS preflight requests.

## 3. TLS/SSL Configuration

### Development Certificates

Generate self-signed certificates:
```bash
./scripts/generate_certs.sh
```

Creates:
- `certs/private.key` - Private key (2048-bit RSA)
- `certs/certificate.crt` - Self-signed certificate (365 days validity)

⚠️ **Self-signed certificates are for development only!**

### Production with Nginx

Use Nginx as reverse proxy for SSL termination:

```bash
# Start Nginx with SSL
docker-compose -f docker-compose.nginx.yml up -d
```

Features:
- HTTP to HTTPS redirect
- TLS 1.2 and 1.3 support
- Strong cipher suites
- Security headers (HSTS, X-Frame-Options, etc.)
- Rate limiting at proxy level

### Let's Encrypt (Production)

For production deployments, use Let's Encrypt:

```bash
# Install certbot
apt-get install certbot python3-certbot-nginx

# Obtain certificate
certbot --nginx -d api.example.com

# Auto-renewal (cron job)
0 0 * * * certbot renew --quiet
```

Update `config/nginx/nginx.conf`:
```nginx
ssl_certificate /etc/letsencrypt/live/api.example.com/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;
```

## 4. Secrets Management

### Development

Use `.env` file (add to `.gitignore`):
```bash
API_KEYS=key1,key2,key3
POSTGRES_PASSWORD=dev_password
CLICKHOUSE_PASSWORD=dev_password
```

### Production Options

#### Docker Secrets (Swarm Mode)
```bash
echo "secure_password" | docker secret create postgres_password -
```

#### HashiCorp Vault
```python
import hvac
client = hvac.Client(url='http://vault:8200')
secret = client.secrets.kv.v2.read_secret_version(path='wotr/db')
```

#### AWS Secrets Manager
```python
import boto3
client = boto3.client('secretsmanager')
response = client.get_secret_value(SecretId='wotr/api-key')
```

#### Kubernetes Secrets
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: wotr-secrets
stringData:
  api-key: "your-key-here"
```

See `secrets/README.md` for comprehensive guidance.

## 5. Additional Security Features

### Security Headers

Added via middleware:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Content-Security-Policy: default-src 'self'`
- `Strict-Transport-Security: max-age=31536000` (Nginx)

### Request ID Tracking

Every request gets unique ID:
- Header: `X-Request-ID`
- For debugging and audit trails

### IP Whitelisting

For administrative endpoints:
```python
from security_middleware import check_ip_whitelist

@app.get("/admin")
def admin_endpoint(request: Request):
    check_ip_whitelist(request)
    # ... admin logic
```

## Configuration Summary

### docker-compose.yml Environment Variables

```yaml
environment:
  # Rate limiting
  RATE_LIMIT_DEFAULT: "100/minute"
  RATE_LIMIT_INGEST: "200/minute"
  RATE_LIMIT_STORAGE: "memory://"
  
  # CORS
  CORS_ORIGINS: "http://localhost:3000"
  CORS_ALLOW_CREDENTIALS: "true"
  CORS_ALLOW_METHODS: "GET,POST,PUT,DELETE,OPTIONS"
  
  # Secrets (use secrets manager in production!)
  API_KEYS: "${API_KEYS}"
  POSTGRES_PASSWORD: "${POSTGRES_PASSWORD}"
  CLICKHOUSE_PASSWORD: "${CLICKHOUSE_PASSWORD}"
```

## Testing

### Test Rate Limiting

```bash
# Exceed rate limit
for i in {1..150}; do curl http://localhost:8000/health; done

# Should receive 429 after limit exceeded
```

### Test CORS

```bash
# Preflight request
curl -X OPTIONS http://localhost:8000/ingest \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: POST"

# Check CORS headers in response
```

### Test SSL/TLS

```bash
# Test Nginx SSL
curl -k https://localhost/health

# Check certificate
openssl s_client -connect localhost:443 -showcerts
```

## Security Best Practices

### Production Checklist

- [ ] Use strong, randomly generated API keys (32+ characters)
- [ ] Store secrets in dedicated secrets manager (not env vars)
- [ ] Enable TLS 1.3 only (disable TLS 1.2 if possible)
- [ ] Use proper CA-signed certificates (Let's Encrypt)
- [ ] Configure rate limiting appropriate for your load
- [ ] Restrict CORS origins to specific domains
- [ ] Enable rate limiting at multiple layers (app + proxy)
- [ ] Implement request signing for critical endpoints
- [ ] Set up WAF (Web Application Firewall) rules
- [ ] Regular security audits and penetration testing
- [ ] Monitor for suspicious activity patterns
- [ ] Implement automated secret rotation
- [ ] Use IP whitelisting for admin endpoints
- [ ] Enable audit logging for all API access
- [ ] Configure DDoS protection (Cloudflare, AWS Shield)

### Monitoring Security Events

Track in Prometheus/Grafana:
- Rate limit violations
- Failed authentication attempts
- Unusual traffic patterns
- Certificate expiration dates

```python
# Example metrics
RATE_LIMIT_EXCEEDED = Counter("rate_limit_exceeded_total", "Rate limit violations")
AUTH_FAILURES = Counter("auth_failures_total", "Failed authentication attempts")
```

## Troubleshooting

### Rate Limiting Issues

If legitimate traffic is being rate-limited:
1. Increase limits via environment variables
2. Use Redis for distributed rate limiting across instances
3. Implement API key-based tiering (different limits per key)

### CORS Errors

If CORS errors occur:
1. Check browser console for specific error
2. Verify `CORS_ORIGINS` includes requesting domain
3. Ensure credentials are properly configured
4. Check for preflight request success

### SSL Certificate Issues

For self-signed certificates:
```bash
# Accept self-signed in curl
curl -k https://localhost/health

# Import certificate to browser trust store
```

For Let's Encrypt:
```bash
# Check certificate status
certbot certificates

# Test renewal
certbot renew --dry-run
```

## References

- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [slowapi Documentation](https://slowapi.readthedocs.io/)
- [Let's Encrypt](https://letsencrypt.org/)
- [Mozilla SSL Configuration Generator](https://ssl-config.mozilla.org/)
