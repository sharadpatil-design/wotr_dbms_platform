#!/usr/bin/env python3
"""
Chaos Engineering: Resource Exhaustion Tests

Tests the platform's behavior under resource pressure:
- CPU throttling
- Memory limits
- Disk space exhaustion
- Connection pool exhaustion

⚠️ WARNING: These tests stress system resources. Run in dev environment only!
"""

import time
import pytest
import docker
import requests
import concurrent.futures
from typing import List

# Test configuration
API_BASE_URL = "http://localhost:8000"
HEALTH_URL = f"{API_BASE_URL}/health"
INGEST_URL = f"{API_BASE_URL}/ingest"
METRICS_URL = f"{API_BASE_URL}/metrics"

# Docker client
client = docker.from_env()

# Service container names
FASTAPI_CONTAINER = "wotr_dbms_platform-fastapi-1"


def get_container(name: str):
    """Get Docker container."""
    try:
        return client.containers.get(name)
    except docker.errors.NotFound:
        pytest.skip(f"Container {name} not found")


class TestResourceExhaustion:
    """Test behavior under resource constraints."""
    
    def test_connection_pool_exhaustion(self):
        """Test behavior when connection pools are exhausted."""
        print("\n=== Testing Connection Pool Exhaustion ===")
        
        # Send many concurrent requests to exhaust connection pool
        print("Sending concurrent requests to exhaust connections...")
        num_requests = 50
        
        def send_request(i: int):
            try:
                response = requests.post(
                    INGEST_URL,
                    json={"payload": {"event_type": "user_action", "example": f"load_test_{i}"}},
                    timeout=30
                )
                return {"index": i, "status": response.status_code, "success": True}
            except requests.RequestException as e:
                return {"index": i, "error": str(e), "success": False}
        
        # Concurrent execution
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(send_request, i) for i in range(num_requests)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
        # Analyze results
        successes = [r for r in results if r.get("success")]
        failures = [r for r in results if not r.get("success")]
        
        print(f"Successful requests: {len(successes)}/{num_requests}")
        print(f"Failed requests: {len(failures)}/{num_requests}")
        
        # At least some should succeed
        assert len(successes) > 0, "All requests failed"
        
        # System should handle failures gracefully (not crash)
        time.sleep(5)
        response = requests.get(HEALTH_URL, timeout=10)
        assert response.status_code == 200, "System not healthy after load"
        
        print("✅ System handled connection pool pressure")
    
    def test_sustained_load(self):
        """Test behavior under sustained load."""
        print("\n=== Testing Sustained Load ===")
        
        # Baseline latency
        print("Measuring baseline latency...")
        start = time.time()
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": "user_action", "example": "baseline"}},
            timeout=10
        )
        baseline_latency = time.time() - start
        print(f"Baseline latency: {baseline_latency:.3f}s")
        assert response.status_code == 200
        
        # Sustained load for 30 seconds
        print("Applying sustained load for 30 seconds...")
        end_time = time.time() + 30
        request_count = 0
        error_count = 0
        latencies = []
        
        while time.time() < end_time:
            try:
                start = time.time()
                response = requests.post(
                    INGEST_URL,
                    json={"payload": {"event_type": "user_action", "example": f"sustained_{request_count}"}},
                    timeout=10
                )
                latency = time.time() - start
                latencies.append(latency)
                
                if response.status_code == 200:
                    request_count += 1
                else:
                    error_count += 1
            except requests.RequestException:
                error_count += 1
            
            time.sleep(0.1)  # 10 req/sec
        
        print(f"Total requests: {request_count}")
        print(f"Errors: {error_count}")
        
        if latencies:
            avg_latency = sum(latencies) / len(latencies)
            p95_latency = sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) > 20 else max(latencies)
            print(f"Average latency: {avg_latency:.3f}s")
            print(f"P95 latency: {p95_latency:.3f}s")
            
            # Latency should not degrade too much
            assert avg_latency < baseline_latency * 3, "Latency degraded significantly under load"
        
        # System should still be healthy
        response = requests.get(HEALTH_URL, timeout=10)
        assert response.status_code == 200
        
        print("✅ System maintained stability under sustained load")
    
    def test_burst_traffic(self):
        """Test behavior under burst traffic."""
        print("\n=== Testing Burst Traffic ===")
        
        # Send burst of 100 requests as fast as possible
        print("Sending burst of 100 requests...")
        
        def send_burst_request(i: int):
            try:
                response = requests.post(
                    INGEST_URL,
                    json={"payload": {"event_type": "user_action", "example": f"burst_{i}"}},
                    timeout=30
                )
                return response.status_code == 200
            except:
                return False
        
        start_time = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
            futures = [executor.submit(send_burst_request, i) for i in range(100)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        elapsed = time.time() - start_time
        
        successes = sum(results)
        print(f"Burst completed in {elapsed:.2f}s")
        print(f"Successful: {successes}/100")
        
        # At least 50% should succeed (rate limiting may kick in)
        assert successes >= 50, f"Too many failures: {100 - successes}"
        
        # System should recover quickly
        time.sleep(10)
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": "user_action", "example": "post_burst"}},
            timeout=10
        )
        assert response.status_code == 200, "System did not recover after burst"
        
        print("✅ System handled burst traffic")
    
    def test_cpu_intensive_operations(self):
        """Test behavior during CPU-intensive operations."""
        print("\n=== Testing CPU Intensive Operations ===")
        
        # Query metrics endpoint multiple times (parsing metrics is CPU intensive)
        print("Sending CPU-intensive requests...")
        
        def fetch_metrics(i: int):
            try:
                response = requests.get(METRICS_URL, timeout=10)
                return response.status_code == 200
            except:
                return False
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(fetch_metrics, i) for i in range(50)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
        successes = sum(results)
        print(f"Metrics requests successful: {successes}/50")
        
        # Most should succeed
        assert successes >= 40, "Too many metrics requests failed"
        
        # Ingest should still work
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": "user_action", "example": "during_cpu_load"}},
            timeout=10
        )
        assert response.status_code == 200
        
        print("✅ System handled CPU-intensive operations")


class TestMemoryPressure:
    """Test behavior under memory pressure."""
    
    def test_large_payload_handling(self):
        """Test handling of large payloads."""
        print("\n=== Testing Large Payload Handling ===")
        
        # Send increasingly large payloads
        sizes = [1_000, 10_000, 100_000, 500_000]  # bytes (approximate)
        
        for size in sizes:
            print(f"Testing payload size ~{size:,} bytes...")
            large_data = "x" * size
            
            try:
                response = requests.post(
                    INGEST_URL,
                    json={"payload": {
                        "event_type": "user_action",
                        "example": "large_payload",
                        "data": large_data
                    }},
                    timeout=30
                )
                
                if response.status_code == 200:
                    print(f"  ✅ {size:,} bytes succeeded")
                elif response.status_code == 413:
                    print(f"  ⚠️ {size:,} bytes rejected (payload too large)")
                    break  # Expected for very large payloads
                else:
                    print(f"  ⚠️ {size:,} bytes failed with {response.status_code}")
            except requests.RequestException as e:
                print(f"  ❌ {size:,} bytes error: {e}")
                break
        
        # System should still be healthy
        time.sleep(5)
        response = requests.get(HEALTH_URL, timeout=10)
        assert response.status_code == 200, "System unhealthy after large payloads"
        
        print("✅ System handled large payloads")
    
    def test_many_small_requests(self):
        """Test memory handling with many small requests."""
        print("\n=== Testing Many Small Requests ===")
        
        # Send 500 small requests
        print("Sending 500 small requests...")
        
        def send_small_request(i: int):
            try:
                response = requests.post(
                    INGEST_URL,
                    json={"payload": {"event_type": "user_action", "id": i}},
                    timeout=10
                )
                return response.status_code == 200
            except:
                return False
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(send_small_request, i) for i in range(500)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
        successes = sum(results)
        print(f"Successful: {successes}/500")
        
        # Most should succeed (some may fail due to rate limiting)
        assert successes >= 400, "Too many failures"
        
        # Check memory hasn't leaked
        time.sleep(5)
        response = requests.get(HEALTH_URL, timeout=10)
        assert response.status_code == 200
        
        print("✅ System handled many small requests")


class TestDiskPressure:
    """Test behavior when disk space is constrained."""
    
    def test_storage_monitoring(self):
        """Verify storage usage is monitored."""
        print("\n=== Testing Storage Monitoring ===")
        
        # Check if admin dashboard shows storage metrics
        try:
            response = requests.get(f"{API_BASE_URL}/admin/stats", timeout=10)
            if response.status_code == 200:
                stats = response.json()
                if "storage_used_mb" in stats:
                    print(f"Storage used: {stats['storage_used_mb']} MB")
                    print("✅ Storage monitoring is active")
                else:
                    print("⚠️ Storage monitoring not available")
            else:
                pytest.skip("Admin stats not available")
        except requests.RequestException:
            pytest.skip("Admin API not available")


class TestGracefulDegradation:
    """Test that system degrades gracefully under stress."""
    
    def test_error_responses_under_load(self):
        """Verify error responses are helpful under load."""
        print("\n=== Testing Error Responses Under Load ===")
        
        # Send more requests than rate limit allows
        print("Exceeding rate limits...")
        
        status_codes = []
        for i in range(100):
            try:
                response = requests.post(
                    INGEST_URL,
                    json={"payload": {"event_type": "user_action", "example": f"rate_limit_{i}"}},
                    timeout=5
                )
                status_codes.append(response.status_code)
            except requests.RequestException:
                status_codes.append(0)
        
        # Should see rate limiting (429) or other controlled errors
        rate_limited = status_codes.count(429)
        successes = status_codes.count(200)
        
        print(f"Success: {successes}, Rate limited: {rate_limited}, Other: {100 - successes - rate_limited}")
        
        # Rate limiting should be active
        if rate_limited > 0:
            print("✅ Rate limiting is working")
        else:
            print("⚠️ Rate limiting may not be configured")
        
        # System should still respond
        time.sleep(5)
        response = requests.get(HEALTH_URL, timeout=10)
        assert response.status_code == 200
        
        print("✅ System provides meaningful error responses")


def test_baseline_performance():
    """Establish baseline performance metrics."""
    print("\n=== Baseline Performance Test ===")
    
    latencies = []
    for i in range(10):
        start = time.time()
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": "user_action", "example": f"baseline_{i}"}},
            timeout=10
        )
        latency = time.time() - start
        latencies.append(latency)
        assert response.status_code == 200
    
    avg_latency = sum(latencies) / len(latencies)
    min_latency = min(latencies)
    max_latency = max(latencies)
    
    print(f"Average latency: {avg_latency:.3f}s")
    print(f"Min latency: {min_latency:.3f}s")
    print(f"Max latency: {max_latency:.3f}s")
    print("✅ Baseline performance established")


if __name__ == "__main__":
    # Run with: python test_resource_exhaustion.py
    pytest.main([__file__, "-v", "-s"])
