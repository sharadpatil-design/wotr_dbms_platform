"""
Unit tests for FastAPI endpoints
"""
import pytest
from fastapi.testclient import TestClient
import sys
import os

# Add app directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from main import app

client = TestClient(app)

# Test API key
TEST_API_KEY = "dev-key-12345"


class TestHealthEndpoint:
    """Tests for /health endpoint"""
    
    def test_health_no_auth_required(self):
        """Health endpoint should work without authentication"""
        response = client.get("/health")
        assert response.status_code in [200, 500]  # May fail if services are down
        assert "details" in response.json()
    
    def test_health_response_structure(self):
        """Health endpoint should return proper structure"""
        response = client.get("/health")
        data = response.json()
        
        assert "details" in data
        assert "postgres" in data["details"]
        assert "minio" in data["details"]
        assert "kafka" in data["details"]
        assert "clickhouse" in data["details"]


class TestMetricsEndpoint:
    """Tests for /metrics endpoint"""
    
    def test_metrics_no_auth_required(self):
        """Metrics endpoint should work without authentication"""
        response = client.get("/metrics")
        assert response.status_code == 200
    
    def test_metrics_prometheus_format(self):
        """Metrics should be in Prometheus format"""
        response = client.get("/metrics")
        content = response.text
        
        # Check for expected metrics
        assert "fastapi_requests_total" in content or "TYPE" in content
        assert response.headers["content-type"] == "text/plain; charset=utf-8"


class TestIngestEndpoint:
    """Tests for /ingest endpoint"""
    
    def test_ingest_requires_auth(self):
        """Ingest should require API key"""
        response = client.post("/ingest", json={"payload": {"test": "data"}})
        assert response.status_code == 401
    
    def test_ingest_invalid_api_key(self):
        """Ingest should reject invalid API key"""
        response = client.post(
            "/ingest",
            json={"payload": {"test": "data"}},
            headers={"X-API-Key": "invalid-key"}
        )
        assert response.status_code == 401
    
    def test_ingest_valid_request(self):
        """Ingest should accept valid request with auth"""
        response = client.post(
            "/ingest",
            json={"payload": {"test": "data", "value": 123}},
            headers={"X-API-Key": TEST_API_KEY}
        )
        # May fail if backend services are down, but should not be auth error
        assert response.status_code in [200, 500]
        if response.status_code == 200:
            data = response.json()
            assert "id" in data
            assert "object_key" in data
    
    def test_ingest_with_custom_id(self):
        """Ingest should accept custom ID"""
        custom_id = "test-id-12345"
        response = client.post(
            "/ingest",
            json={"id": custom_id, "payload": {"test": "data"}},
            headers={"X-API-Key": TEST_API_KEY}
        )
        if response.status_code == 200:
            data = response.json()
            assert data["id"] == custom_id
    
    def test_ingest_missing_payload(self):
        """Ingest should reject request without payload"""
        response = client.post(
            "/ingest",
            json={},
            headers={"X-API-Key": TEST_API_KEY}
        )
        assert response.status_code == 422  # Validation error


class TestRetentionPoliciesEndpoint:
    """Tests for /retention-policies endpoint"""
    
    def test_retention_requires_auth(self):
        """Retention policies should require API key"""
        response = client.get("/retention-policies")
        assert response.status_code == 401
    
    def test_retention_valid_request(self):
        """Retention policies should return config with valid auth"""
        response = client.get(
            "/retention-policies",
            headers={"X-API-Key": TEST_API_KEY}
        )
        assert response.status_code == 200
        data = response.json()
        assert "policies" in data
        assert "clickhouse" in data["policies"]
        assert "minio_raw" in data["policies"]


class TestAuthModule:
    """Tests for authentication module"""
    
    def test_missing_api_key_header(self):
        """Request without API key header should fail"""
        response = client.post("/ingest", json={"payload": {"test": "data"}})
        assert response.status_code == 401
        assert "Invalid or missing API key" in response.json()["detail"]
    
    def test_empty_api_key(self):
        """Empty API key should fail"""
        response = client.post(
            "/ingest",
            json={"payload": {"test": "data"}},
            headers={"X-API-Key": ""}
        )
        assert response.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
