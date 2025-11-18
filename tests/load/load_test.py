"""
Load testing script using Locust
Tests FastAPI /ingest endpoint performance under load
"""
from locust import HttpUser, task, between
import random
import json


class IngestUser(HttpUser):
    """Simulated user performing ingest operations"""
    
    wait_time = between(1, 3)  # Wait 1-3 seconds between requests
    
    def on_start(self):
        """Called when a user starts"""
        self.headers = {
            "Content-Type": "application/json",
            "X-API-Key": "dev-key-12345"
        }
    
    @task(10)
    def ingest_event(self):
        """Main ingest task (weight: 10)"""
        payload = {
            "payload": {
                "event_type": random.choice(["click", "view", "purchase", "signup"]),
                "user_id": f"user_{random.randint(1, 1000)}",
                "timestamp": "2025-11-18T12:00:00Z",
                "value": random.randint(1, 100),
                "metadata": {
                    "source": random.choice(["web", "mobile", "api"]),
                    "version": "1.0"
                }
            }
        }
        
        with self.client.post(
            "/ingest",
            json=payload,
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Failed with status {response.status_code}")
    
    @task(2)
    def check_health(self):
        """Health check task (weight: 2, less frequent)"""
        with self.client.get("/health", catch_response=True) as response:
            if response.status_code in [200, 500]:  # 500 ok if services down
                response.success()
            else:
                response.failure(f"Unexpected status {response.status_code}")
    
    @task(1)
    def get_metrics(self):
        """Metrics endpoint task (weight: 1, least frequent)"""
        self.client.get("/metrics")


class HighVolumeIngestUser(HttpUser):
    """User simulating high-volume ingest scenario"""
    
    wait_time = between(0.1, 0.5)  # Very short wait time for high throughput
    
    def on_start(self):
        self.headers = {
            "Content-Type": "application/json",
            "X-API-Key": "dev-key-12345"
        }
    
    @task
    def rapid_ingest(self):
        """Rapid fire ingest requests"""
        payload = {
            "payload": {
                "event": "high_volume_test",
                "value": random.random() * 1000
            }
        }
        self.client.post("/ingest", json=payload, headers=self.headers)


class ReadHeavyUser(HttpUser):
    """User that mostly reads (health/metrics checks)"""
    
    wait_time = between(1, 2)
    
    @task(5)
    def check_health(self):
        self.client.get("/health")
    
    @task(5)
    def get_metrics(self):
        self.client.get("/metrics")
    
    @task(1)
    def check_retention(self):
        """Occasional retention policy check"""
        self.client.get(
            "/retention-policies",
            headers={"X-API-Key": "dev-key-12345"}
        )


# Run configuration examples:
# 
# Basic load test (10 users, 2 users/sec spawn rate):
#   locust -f load_test.py --host http://localhost:8000 -u 10 -r 2 --run-time 1m --headless
#
# High load (100 users, 10 users/sec spawn rate, 5 minute test):
#   locust -f load_test.py --host http://localhost:8000 -u 100 -r 10 --run-time 5m --headless
#
# Stress test (1000 users, 50 users/sec):
#   locust -f load_test.py --host http://localhost:8000 -u 1000 -r 50 --run-time 10m --headless
#
# With web UI (access at http://localhost:8089):
#   locust -f load_test.py --host http://localhost:8000
