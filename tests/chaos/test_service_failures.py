#!/usr/bin/env python3
"""
Chaos Engineering: Service Failure Tests

Tests the platform's resilience to individual service failures.
Validates health checks, automatic recovery, and graceful degradation.

⚠️ WARNING: These tests stop and restart services. Run in dev environment only!
"""

import time
import pytest
import docker
import requests
from typing import Dict, List

# Test configuration
API_BASE_URL = "http://localhost:8000"
ADMIN_URL = f"{API_BASE_URL}/admin"
HEALTH_URL = f"{API_BASE_URL}/health"
INGEST_URL = f"{API_BASE_URL}/ingest"

# Docker client
client = docker.from_env()

# Service container names (adjust based on docker-compose project name)
SERVICES = {
    "fastapi": "wotr_dbms_platform-fastapi-1",
    "postgres": "wotr_dbms_platform-postgres-1",
    "clickhouse": "wotr_dbms_platform-clickhouse-1",
    "minio": "wotr_dbms_platform-minio-1",
    "redpanda": "wotr_dbms_platform-redpanda-1",
    "consumer": "wotr_dbms_platform-consumer-1",
}


def get_container(service_name: str):
    """Get Docker container by service name."""
    try:
        return client.containers.get(SERVICES[service_name])
    except docker.errors.NotFound:
        pytest.skip(f"Container {SERVICES[service_name]} not found. Is docker-compose running?")


def wait_for_health(url: str, timeout: int = 60, expected_status: int = 200) -> bool:
    """Wait for service to become healthy."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == expected_status:
                return True
        except requests.RequestException:
            pass
        time.sleep(2)
    return False


def get_service_health() -> Dict:
    """Get service health status from admin API."""
    try:
        response = requests.get(f"{ADMIN_URL}/services", timeout=10)
        if response.status_code == 200:
            return {svc["service"]: svc["status"] for svc in response.json()}
        return {}
    except requests.RequestException:
        return {}


@pytest.fixture(scope="function")
def ensure_services_running():
    """Fixture to ensure all services are running before and after each test."""
    # Before test: ensure all running
    for service_name, container_name in SERVICES.items():
        try:
            container = client.containers.get(container_name)
            if container.status != "running":
                print(f"Starting {service_name}...")
                container.start()
        except docker.errors.NotFound:
            pytest.skip(f"Container {container_name} not found")
    
    # Wait for system to be healthy
    assert wait_for_health(HEALTH_URL, timeout=60), "System not healthy before test"
    
    yield
    
    # After test: restore all services
    for service_name, container_name in SERVICES.items():
        try:
            container = client.containers.get(container_name)
            if container.status != "running":
                print(f"Recovering {service_name}...")
                container.start()
        except Exception as e:
            print(f"Error recovering {service_name}: {e}")
    
    # Wait for recovery
    wait_for_health(HEALTH_URL, timeout=60)


class TestServiceFailures:
    """Test suite for service failure scenarios."""
    
    def test_fastapi_restart(self, ensure_services_running):
        """Test FastAPI service restart."""
        print("\n=== Testing FastAPI Restart ===")
        
        # Baseline: verify healthy
        response = requests.get(HEALTH_URL)
        assert response.status_code == 200, "System not healthy before test"
        
        # Chaos: stop FastAPI
        print("Stopping FastAPI...")
        container = get_container("fastapi")
        container.stop()
        time.sleep(5)
        
        # Observe: API should be unreachable
        print("Verifying API is down...")
        with pytest.raises(requests.RequestException):
            requests.get(HEALTH_URL, timeout=5)
        
        # Recover: restart FastAPI
        print("Restarting FastAPI...")
        container.start()
        
        # Validate: should recover
        print("Waiting for recovery...")
        assert wait_for_health(HEALTH_URL, timeout=60), "FastAPI did not recover"
        
        print("✅ FastAPI recovered successfully")
    
    def test_postgres_failure(self, ensure_services_running):
        """Test Postgres failure and recovery."""
        print("\n=== Testing Postgres Failure ===")
        
        # Baseline
        health = get_service_health()
        assert health.get("postgresql") == "ok", "Postgres not healthy before test"
        
        # Chaos: stop Postgres
        print("Stopping Postgres...")
        container = get_container("postgres")
        container.stop()
        time.sleep(10)
        
        # Observe: health check should detect failure
        print("Checking service health...")
        health = get_service_health()
        # FastAPI should still respond, but postgres health should fail
        assert health.get("postgresql") != "ok", "Health check did not detect Postgres failure"
        
        # Ingestion should fail gracefully
        print("Testing ingest during Postgres failure...")
        try:
            response = requests.post(
                INGEST_URL,
                json={"payload": {"event_type": "user_action", "example": "chaos_test"}},
                timeout=5
            )
            # Should get error response, not hang
            assert response.status_code in [500, 503], f"Expected error, got {response.status_code}"
        except requests.Timeout:
            pytest.fail("Ingest request timed out instead of failing gracefully")
        
        # Recover: restart Postgres
        print("Restarting Postgres...")
        container.start()
        time.sleep(15)  # Postgres needs time to start
        
        # Validate: should recover
        print("Waiting for recovery...")
        recovered = False
        for _ in range(30):  # Try for 60 seconds
            health = get_service_health()
            if health.get("postgresql") == "ok":
                recovered = True
                break
            time.sleep(2)
        
        assert recovered, "Postgres did not recover"
        print("✅ Postgres recovered successfully")
    
    def test_clickhouse_failure(self, ensure_services_running):
        """Test ClickHouse failure and consumer behavior."""
        print("\n=== Testing ClickHouse Failure ===")
        
        # Baseline
        health = get_service_health()
        assert health.get("clickhouse") == "ok", "ClickHouse not healthy before test"
        
        # Chaos: stop ClickHouse
        print("Stopping ClickHouse...")
        container = get_container("clickhouse")
        container.stop()
        time.sleep(10)
        
        # Observe: health check should detect failure
        print("Checking service health...")
        health = get_service_health()
        assert health.get("clickhouse") != "ok", "Health check did not detect ClickHouse failure"
        
        # Consumer should handle failure (messages go to DLQ)
        print("Testing ingest during ClickHouse failure...")
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": "user_action", "example": "chaos_test_ch"}},
            timeout=10
        )
        # Ingest to Kafka should still work
        assert response.status_code == 200, "Ingest should succeed even if ClickHouse down"
        
        # Recover: restart ClickHouse
        print("Restarting ClickHouse...")
        container.start()
        time.sleep(20)  # ClickHouse needs time to start
        
        # Validate: should recover
        print("Waiting for recovery...")
        recovered = False
        for _ in range(30):
            health = get_service_health()
            if health.get("clickhouse") == "ok":
                recovered = True
                break
            time.sleep(2)
        
        assert recovered, "ClickHouse did not recover"
        print("✅ ClickHouse recovered successfully")
    
    def test_minio_failure(self, ensure_services_running):
        """Test MinIO failure and graceful degradation."""
        print("\n=== Testing MinIO Failure ===")
        
        # Baseline
        health = get_service_health()
        assert health.get("minio") == "ok", "MinIO not healthy before test"
        
        # Chaos: stop MinIO
        print("Stopping MinIO...")
        container = get_container("minio")
        container.stop()
        time.sleep(10)
        
        # Observe: health check should detect failure
        print("Checking service health...")
        health = get_service_health()
        assert health.get("minio") != "ok", "Health check did not detect MinIO failure"
        
        # Ingest should fail gracefully
        print("Testing ingest during MinIO failure...")
        try:
            response = requests.post(
                INGEST_URL,
                json={"payload": {"event_type": "user_action", "example": "chaos_test_minio"}},
                timeout=10
            )
            # Should get error response
            assert response.status_code in [500, 503], f"Expected error, got {response.status_code}"
        except requests.Timeout:
            pytest.fail("Ingest timed out instead of failing gracefully")
        
        # Recover: restart MinIO
        print("Restarting MinIO...")
        container.start()
        time.sleep(10)
        
        # Validate: should recover
        print("Waiting for recovery...")
        recovered = False
        for _ in range(30):
            health = get_service_health()
            if health.get("minio") == "ok":
                recovered = True
                break
            time.sleep(2)
        
        assert recovered, "MinIO did not recover"
        print("✅ MinIO recovered successfully")
    
    def test_kafka_failure(self, ensure_services_running):
        """Test Kafka/Redpanda failure."""
        print("\n=== Testing Kafka Failure ===")
        
        # Baseline
        health = get_service_health()
        assert health.get("kafka") == "ok", "Kafka not healthy before test"
        
        # Chaos: stop Redpanda
        print("Stopping Redpanda...")
        container = get_container("redpanda")
        container.stop()
        time.sleep(10)
        
        # Observe: ingest should fail
        print("Testing ingest during Kafka failure...")
        try:
            response = requests.post(
                INGEST_URL,
                json={"payload": {"event_type": "user_action", "example": "chaos_test_kafka"}},
                timeout=10
            )
            # Should get error response
            assert response.status_code in [500, 503], f"Expected error, got {response.status_code}"
        except requests.Timeout:
            pytest.fail("Ingest timed out instead of failing gracefully")
        
        # Recover: restart Redpanda
        print("Restarting Redpanda...")
        container.start()
        time.sleep(20)  # Kafka needs time to start
        
        # Validate: should recover
        print("Waiting for recovery...")
        assert wait_for_health(HEALTH_URL, timeout=60), "System did not recover after Kafka restart"
        
        print("✅ Kafka recovered successfully")
    
    def test_consumer_failure(self, ensure_services_running):
        """Test consumer failure and automatic restart."""
        print("\n=== Testing Consumer Failure ===")
        
        # Baseline: ingest should work
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": "user_action", "example": "before_consumer_stop"}},
            timeout=10
        )
        assert response.status_code == 200
        
        # Chaos: stop consumer
        print("Stopping Consumer...")
        container = get_container("consumer")
        container.stop()
        time.sleep(5)
        
        # Observe: ingest should still work (Kafka buffers messages)
        print("Testing ingest during consumer failure...")
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": "user_action", "example": "during_consumer_stop"}},
            timeout=10
        )
        assert response.status_code == 200, "Ingest should work even if consumer down"
        
        # Recover: restart consumer
        print("Restarting Consumer...")
        container.start()
        time.sleep(10)
        
        # Validate: consumer should catch up
        # (In production, would check consumer lag here)
        print("✅ Consumer restarted successfully")


class TestCascadingFailures:
    """Test cascading failure scenarios."""
    
    def test_multiple_service_failures(self, ensure_services_running):
        """Test failure of multiple services simultaneously."""
        print("\n=== Testing Multiple Service Failures ===")
        
        # Baseline
        assert wait_for_health(HEALTH_URL, timeout=30), "System not healthy"
        
        # Chaos: stop multiple services
        print("Stopping Postgres and ClickHouse...")
        postgres = get_container("postgres")
        clickhouse = get_container("clickhouse")
        
        postgres.stop()
        clickhouse.stop()
        time.sleep(10)
        
        # Observe: system should detect both failures
        print("Checking service health...")
        health = get_service_health()
        assert health.get("postgresql") != "ok", "Did not detect Postgres failure"
        assert health.get("clickhouse") != "ok", "Did not detect ClickHouse failure"
        
        # Recover: restart both
        print("Restarting services...")
        postgres.start()
        clickhouse.start()
        time.sleep(30)
        
        # Validate: both should recover
        print("Waiting for recovery...")
        assert wait_for_health(HEALTH_URL, timeout=90), "System did not recover from multiple failures"
        
        print("✅ System recovered from multiple failures")


def test_baseline_health():
    """Baseline test: verify system is healthy before running chaos tests."""
    print("\n=== Baseline Health Check ===")
    
    # Check API is reachable
    try:
        response = requests.get(HEALTH_URL, timeout=10)
        assert response.status_code == 200, f"Health check failed: {response.status_code}"
        print("✅ API is healthy")
    except requests.RequestException as e:
        pytest.fail(f"API not reachable: {e}")
    
    # Check all services are healthy
    try:
        response = requests.get(f"{ADMIN_URL}/services", timeout=10)
        if response.status_code == 200:
            services = response.json()
            for svc in services:
                print(f"  {svc['service']}: {svc['status']}")
                assert svc["status"] == "ok", f"{svc['service']} is not healthy"
            print("✅ All services are healthy")
    except requests.RequestException as e:
        pytest.fail(f"Admin API not reachable: {e}")


if __name__ == "__main__":
    # Run with: python test_service_failures.py
    pytest.main([__file__, "-v", "-s"])
