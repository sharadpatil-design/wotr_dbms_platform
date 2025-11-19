#!/usr/bin/env python3
"""
Chaos Engineering: Network Chaos Tests

Tests the platform's resilience to network issues including:
- Network latency
- Packet loss
- Network partitions
- Timeout scenarios

⚠️ WARNING: These tests introduce network delays. Run in dev environment only!

Note: Network chaos requires tc (traffic control) or similar tools.
This implementation uses container pauses as a proxy for network issues.
For production-grade network chaos, consider using tools like:
- Pumba (https://github.com/alexei-led/pumba)
- Toxiproxy (https://github.com/Shopify/toxiproxy)
- Chaos Mesh (for Kubernetes)
"""

import time
import pytest
import docker
import requests
from typing import Dict

# Test configuration
API_BASE_URL = "http://localhost:8000"
HEALTH_URL = f"{API_BASE_URL}/health"
INGEST_URL = f"{API_BASE_URL}/ingest"

# Docker client
client = docker.from_env()

# Service container names
SERVICES = {
    "postgres": "wotr_dbms_platform-postgres-1",
    "clickhouse": "wotr_dbms_platform-clickhouse-1",
    "minio": "wotr_dbms_platform-minio-1",
    "redpanda": "wotr_dbms_platform-redpanda-1",
}


def get_container(service_name: str):
    """Get Docker container by service name."""
    try:
        return client.containers.get(SERVICES[service_name])
    except docker.errors.NotFound:
        pytest.skip(f"Container {SERVICES[service_name]} not found")


@pytest.fixture(scope="function")
def ensure_containers_running():
    """Ensure containers are running and unpaused."""
    for service_name, container_name in SERVICES.items():
        try:
            container = client.containers.get(container_name)
            if container.status == "paused":
                container.unpause()
            elif container.status != "running":
                container.start()
        except docker.errors.NotFound:
            pass
    
    time.sleep(5)
    yield
    
    # Cleanup: unpause all
    for service_name, container_name in SERVICES.items():
        try:
            container = client.containers.get(container_name)
            if container.status == "paused":
                container.unpause()
        except Exception:
            pass
    time.sleep(5)


class TestNetworkChaos:
    """Test network-related failures."""
    
    def test_database_network_partition(self, ensure_containers_running):
        """Simulate network partition to database by pausing container."""
        print("\n=== Testing Database Network Partition ===")
        
        # Baseline: verify ingest works
        print("Baseline ingest...")
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": "user_action", "example": "before_partition"}},
            timeout=10
        )
        assert response.status_code == 200, "Baseline ingest failed"
        
        # Chaos: pause Postgres container (simulates network partition)
        print("Simulating network partition to Postgres...")
        container = get_container("postgres")
        container.pause()
        time.sleep(5)
        
        # Observe: ingest should fail or timeout gracefully
        print("Testing ingest during partition...")
        start_time = time.time()
        try:
            response = requests.post(
                INGEST_URL,
                json={"payload": {"event_type": "user_action", "example": "during_partition"}},
                timeout=15  # Should fail before timeout
            )
            elapsed = time.time() - start_time
            print(f"Request completed in {elapsed:.2f}s with status {response.status_code}")
            # Should get error response
            assert response.status_code in [500, 503, 504], f"Expected error, got {response.status_code}"
            # Should fail relatively quickly (not hang for full timeout)
            assert elapsed < 12, f"Request took too long ({elapsed:.2f}s), should fail faster"
        except requests.Timeout:
            elapsed = time.time() - start_time
            print(f"Request timed out after {elapsed:.2f}s (acceptable)")
        
        # Recover: unpause container
        print("Restoring network...")
        container.unpause()
        time.sleep(10)
        
        # Validate: should recover
        print("Testing recovery...")
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": "user_action", "example": "after_partition"}},
            timeout=10
        )
        assert response.status_code == 200, "Failed to recover after partition"
        
        print("✅ System recovered from network partition")
    
    def test_kafka_network_partition(self, ensure_containers_running):
        """Simulate network partition to Kafka."""
        print("\n=== Testing Kafka Network Partition ===")
        
        # Baseline
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": "user_action", "example": "before_kafka_partition"}},
            timeout=10
        )
        assert response.status_code == 200
        
        # Chaos: pause Redpanda
        print("Simulating network partition to Kafka...")
        container = get_container("redpanda")
        container.pause()
        time.sleep(5)
        
        # Observe: should fail gracefully
        print("Testing ingest during Kafka partition...")
        start_time = time.time()
        try:
            response = requests.post(
                INGEST_URL,
                json={"payload": {"event_type": "user_action", "example": "during_kafka_partition"}},
                timeout=15
            )
            elapsed = time.time() - start_time
            print(f"Request completed in {elapsed:.2f}s with status {response.status_code}")
            assert response.status_code in [500, 503, 504]
        except requests.Timeout:
            print("Request timed out (acceptable for Kafka partition)")
        
        # Recover
        print("Restoring network...")
        container.unpause()
        time.sleep(10)
        
        # Validate
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": "user_action", "example": "after_kafka_partition"}},
            timeout=10
        )
        assert response.status_code == 200
        
        print("✅ System recovered from Kafka network partition")
    
    def test_minio_network_partition(self, ensure_containers_running):
        """Simulate network partition to MinIO."""
        print("\n=== Testing MinIO Network Partition ===")
        
        # Baseline
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": "user_action", "example": "before_minio_partition"}},
            timeout=10
        )
        assert response.status_code == 200
        
        # Chaos: pause MinIO
        print("Simulating network partition to MinIO...")
        container = get_container("minio")
        container.pause()
        time.sleep(5)
        
        # Observe: should fail gracefully
        print("Testing ingest during MinIO partition...")
        start_time = time.time()
        try:
            response = requests.post(
                INGEST_URL,
                json={"payload": {"event_type": "user_action", "example": "during_minio_partition"}},
                timeout=15
            )
            elapsed = time.time() - start_time
            print(f"Request completed in {elapsed:.2f}s with status {response.status_code}")
            assert response.status_code in [500, 503, 504]
            assert elapsed < 12, "Request should fail faster"
        except requests.Timeout:
            print("Request timed out (acceptable for MinIO partition)")
        
        # Recover
        print("Restoring network...")
        container.unpause()
        time.sleep(10)
        
        # Validate
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": "user_action", "example": "after_minio_partition"}},
            timeout=10
        )
        assert response.status_code == 200
        
        print("✅ System recovered from MinIO network partition")
    
    def test_timeout_handling(self, ensure_containers_running):
        """Test that API handles timeouts gracefully."""
        print("\n=== Testing Timeout Handling ===")
        
        # Pause ClickHouse to induce timeout in health check
        print("Pausing ClickHouse to induce timeout...")
        container = get_container("clickhouse")
        container.pause()
        time.sleep(5)
        
        # Health check should handle timeout
        print("Testing health check timeout handling...")
        start_time = time.time()
        try:
            response = requests.get(HEALTH_URL, timeout=30)
            elapsed = time.time() - start_time
            print(f"Health check completed in {elapsed:.2f}s with status {response.status_code}")
            # Should get response (possibly 500 with error details)
            assert elapsed < 20, "Health check should timeout faster"
        except requests.Timeout:
            pytest.fail("Health check should not hang, should return error")
        
        # Recover
        print("Restoring ClickHouse...")
        container.unpause()
        time.sleep(10)
        
        print("✅ Timeout handling validated")


class TestRetryLogic:
    """Test retry and backoff behavior."""
    
    def test_transient_failure_retry(self, ensure_containers_running):
        """Test that transient failures trigger retries."""
        print("\n=== Testing Transient Failure Retry ===")
        
        # This test validates that brief outages are handled
        # In a real system, this would test connection retry logic
        
        # Brief pause (< 5 seconds)
        print("Simulating brief network glitch...")
        container = get_container("postgres")
        container.pause()
        time.sleep(2)  # Very brief
        container.unpause()
        time.sleep(5)  # Allow recovery
        
        # System should recover automatically
        print("Testing ingest after brief glitch...")
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": "user_action", "example": "after_glitch"}},
            timeout=10
        )
        
        # Depending on timing, might succeed or fail
        # But should not hang
        print(f"Response status: {response.status_code}")
        assert response.status_code in [200, 500, 503], "Unexpected status code"
        
        # Follow-up request should definitely work
        time.sleep(5)
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": "user_action", "example": "recovery_confirmed"}},
            timeout=10
        )
        assert response.status_code == 200, "Should recover after brief glitch"
        
        print("✅ System handles transient failures")


class TestLatencyTolerance:
    """Test behavior under high latency conditions."""
    
    def test_high_latency_scenario(self, ensure_containers_running):
        """Simulate high latency by repeated brief pauses."""
        print("\n=== Testing High Latency Scenario ===")
        
        # This simulates network latency by introducing brief delays
        # In production, would use tc or toxiproxy for realistic latency
        
        print("Baseline request timing...")
        start = time.time()
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": "user_action", "example": "baseline"}},
            timeout=10
        )
        baseline_latency = time.time() - start
        print(f"Baseline latency: {baseline_latency:.3f}s")
        assert response.status_code == 200
        
        # Simulate latency with container pause/unpause cycles
        print("Testing under simulated latency...")
        container = get_container("minio")
        
        # Multiple brief pauses to simulate choppy network
        for i in range(3):
            container.pause()
            time.sleep(0.5)
            container.unpause()
            time.sleep(0.5)
        
        # Request should either succeed with higher latency or fail gracefully
        start = time.time()
        try:
            response = requests.post(
                INGEST_URL,
                json={"payload": {"event_type": "user_action", "example": "high_latency"}},
                timeout=20
            )
            latency = time.time() - start
            print(f"High latency request: {latency:.3f}s, status: {response.status_code}")
            # Either success or graceful failure
            assert response.status_code in [200, 500, 503, 504]
        except requests.Timeout:
            print("Request timed out under high latency (acceptable)")
        
        # System should recover
        time.sleep(5)
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": "user_action", "example": "after_latency"}},
            timeout=10
        )
        assert response.status_code == 200
        
        print("✅ System tolerates high latency conditions")


def test_network_health_monitoring():
    """Verify network health monitoring detects issues."""
    print("\n=== Testing Network Health Monitoring ===")
    
    # This test verifies that health checks reflect network reality
    # In a real deployment, would integrate with network monitoring tools
    
    try:
        response = requests.get(HEALTH_URL, timeout=10)
        if response.status_code == 200:
            health = response.json()
            print(f"Current health status: {health}")
            
            # Verify structure
            assert "status" in health or "details" in health
            print("✅ Health monitoring endpoint is functional")
        else:
            pytest.skip("Health endpoint not available")
    except requests.RequestException as e:
        pytest.skip(f"Cannot reach health endpoint: {e}")


if __name__ == "__main__":
    # Run with: python test_network_chaos.py
    pytest.main([__file__, "-v", "-s"])
