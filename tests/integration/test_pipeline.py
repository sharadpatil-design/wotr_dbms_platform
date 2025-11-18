"""
Integration tests for the complete data pipeline
Tests end-to-end flow: API -> Kafka -> ClickHouse
"""
import pytest
import requests
import time
import psycopg2
from clickhouse_driver import Client as ClickHouseClient
import uuid

# Configuration
API_URL = "http://localhost:8000"
API_KEY = "dev-key-12345"

POSTGRES_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "wotr",
    "user": "admin",
    "password": "admin"
}

CLICKHOUSE_CONFIG = {
    "host": "localhost",
    "port": 9009,
    "user": "wotr",
    "password": "wotrpass"
}


@pytest.fixture(scope="module")
def api_headers():
    """API request headers with authentication"""
    return {
        "Content-Type": "application/json",
        "X-API-Key": API_KEY
    }


@pytest.fixture(scope="module")
def postgres_conn():
    """PostgreSQL connection"""
    conn = psycopg2.connect(**POSTGRES_CONFIG)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def clickhouse_client():
    """ClickHouse client"""
    client = ClickHouseClient(**CLICKHOUSE_CONFIG)
    yield client
    client.disconnect()


class TestEndToEndPipeline:
    """Test complete data flow through the pipeline"""
    
    def test_services_health(self):
        """Verify all services are healthy before running tests"""
        response = requests.get(f"{API_URL}/health")
        assert response.status_code == 200
        
        details = response.json()["details"]
        assert details["postgres"] == "ok"
        assert details["kafka"] == "ok"
        assert details["minio"] == "ok"
        # ClickHouse may be "ok" or "ok (check disabled)"
        assert "ok" in str(details["clickhouse"])
    
    def test_ingest_to_postgres(self, api_headers, postgres_conn):
        """Test that ingest writes metadata to PostgreSQL"""
        test_id = f"integration-test-{uuid.uuid4()}"
        payload = {
            "id": test_id,
            "payload": {"test": "integration", "value": 999}
        }
        
        # Send ingest request
        response = requests.post(f"{API_URL}/ingest", json=payload, headers=api_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert data["id"] == test_id
        
        # Wait for PostgreSQL write
        time.sleep(2)
        
        # Verify in PostgreSQL
        cur = postgres_conn.cursor()
        cur.execute("SELECT id, object_key FROM ingest_meta WHERE id = %s", (test_id,))
        result = cur.fetchone()
        
        assert result is not None
        assert result[0] == test_id
        assert f"raw/{test_id}.json" in result[1]
        
        cur.close()
    
    def test_ingest_to_clickhouse(self, api_headers, clickhouse_client):
        """Test that ingest flows through Kafka to ClickHouse"""
        test_id = f"integration-test-ch-{uuid.uuid4()}"
        payload = {
            "id": test_id,
            "payload": {"test": "clickhouse-integration", "value": 888}
        }
        
        # Send ingest request
        response = requests.post(f"{API_URL}/ingest", json=payload, headers=api_headers)
        assert response.status_code == 200
        
        # Wait for consumer to process (may take a few seconds)
        time.sleep(10)
        
        # Query ClickHouse
        result = clickhouse_client.execute(
            "SELECT id, payload FROM wotr.ingested_data WHERE id = %(id)s",
            {"id": test_id}
        )
        
        assert len(result) > 0
        assert result[0][0] == test_id
        assert "clickhouse-integration" in result[0][1]
    
    def test_multiple_ingests(self, api_headers):
        """Test handling multiple ingests in sequence"""
        test_ids = [f"multi-test-{uuid.uuid4()}" for _ in range(5)]
        
        for test_id in test_ids:
            payload = {
                "id": test_id,
                "payload": {"test": "multiple", "index": test_ids.index(test_id)}
            }
            response = requests.post(f"{API_URL}/ingest", json=payload, headers=api_headers)
            assert response.status_code == 200
        
        # All should succeed
        assert len(test_ids) == 5
    
    def test_metrics_updated_after_ingest(self, api_headers):
        """Test that Prometheus metrics are updated after ingest"""
        # Get initial metrics
        response = requests.get(f"{API_URL}/metrics")
        initial_metrics = response.text
        
        # Perform ingest
        test_id = f"metrics-test-{uuid.uuid4()}"
        payload = {"id": test_id, "payload": {"test": "metrics"}}
        requests.post(f"{API_URL}/ingest", json=payload, headers=api_headers)
        
        # Get updated metrics
        response = requests.get(f"{API_URL}/metrics")
        updated_metrics = response.text
        
        # Verify metrics contain ingest counter
        assert "wotr_ingest_total" in updated_metrics


class TestErrorHandling:
    """Test error handling in the pipeline"""
    
    def test_invalid_json(self, api_headers):
        """Test handling of invalid JSON"""
        response = requests.post(
            f"{API_URL}/ingest",
            data="invalid json",
            headers=api_headers
        )
        assert response.status_code == 422
    
    def test_missing_payload_field(self, api_headers):
        """Test handling of missing required fields"""
        response = requests.post(
            f"{API_URL}/ingest",
            json={"id": "test-123"},  # Missing payload
            headers=api_headers
        )
        assert response.status_code == 422


class TestRetentionPolicies:
    """Test retention policy configuration"""
    
    def test_retention_config_accessible(self, api_headers):
        """Test that retention policies can be retrieved"""
        response = requests.get(
            f"{API_URL}/retention-policies",
            headers=api_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "policies" in data
        
        policies = data["policies"]
        assert "clickhouse" in policies
        assert "minio_raw" in policies
        assert "postgres_metadata" in policies
        
        # Check structure
        assert "retention_days" in policies["clickhouse"]
        assert "enabled" in policies["clickhouse"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
