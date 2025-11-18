#!/usr/bin/env python3
"""
Performance benchmark script
Measures baseline performance metrics for the WOTR platform
"""
import time
import statistics
import requests
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

API_URL = "http://localhost:8000"
API_KEY = "dev-key-12345"
HEADERS = {"Content-Type": "application/json", "X-API-Key": API_KEY}


def measure_request(func, *args, **kwargs):
    """Measure execution time of a request"""
    start = time.time()
    result = func(*args, **kwargs)
    duration = time.time() - start
    return result, duration


def benchmark_health_endpoint(num_requests=100):
    """Benchmark /health endpoint"""
    print(f"\n=== Benchmarking /health endpoint ({num_requests} requests) ===")
    durations = []
    
    for i in range(num_requests):
        _, duration = measure_request(requests.get, f"{API_URL}/health")
        durations.append(duration)
    
    print_stats("Health Endpoint", durations)
    return durations


def benchmark_ingest_endpoint(num_requests=100):
    """Benchmark /ingest endpoint"""
    print(f"\n=== Benchmarking /ingest endpoint ({num_requests} requests) ===")
    durations = []
    
    for i in range(num_requests):
        payload = {"payload": {"test": "benchmark", "index": i, "timestamp": datetime.utcnow().isoformat()}}
        _, duration = measure_request(requests.post, f"{API_URL}/ingest", json=payload, headers=HEADERS)
        durations.append(duration)
    
    print_stats("Ingest Endpoint", durations)
    return durations


def benchmark_concurrent_ingests(num_requests=100, workers=10):
    """Benchmark concurrent ingest requests"""
    print(f"\n=== Benchmarking concurrent ingests ({num_requests} requests, {workers} workers) ===")
    durations = []
    
    def send_request(index):
        payload = {"payload": {"test": "concurrent", "index": index}}
        start = time.time()
        response = requests.post(f"{API_URL}/ingest", json=payload, headers=HEADERS)
        duration = time.time() - start
        return response.status_code, duration
    
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(send_request, i) for i in range(num_requests)]
        
        for future in as_completed(futures):
            status, duration = future.result()
            durations.append(duration)
    
    total_time = time.time() - start_time
    
    print_stats("Concurrent Ingests", durations)
    print(f"Total time: {total_time:.2f}s")
    print(f"Throughput: {num_requests / total_time:.2f} req/s")
    
    return durations


def benchmark_metrics_endpoint(num_requests=50):
    """Benchmark /metrics endpoint"""
    print(f"\n=== Benchmarking /metrics endpoint ({num_requests} requests) ===")
    durations = []
    
    for i in range(num_requests):
        _, duration = measure_request(requests.get, f"{API_URL}/metrics")
        durations.append(duration)
    
    print_stats("Metrics Endpoint", durations)
    return durations


def print_stats(name, durations):
    """Print statistics for a set of measurements"""
    if not durations:
        print(f"No data for {name}")
        return
    
    print(f"\n{name} Statistics:")
    print(f"  Total requests: {len(durations)}")
    print(f"  Mean: {statistics.mean(durations) * 1000:.2f}ms")
    print(f"  Median: {statistics.median(durations) * 1000:.2f}ms")
    print(f"  Min: {min(durations) * 1000:.2f}ms")
    print(f"  Max: {max(durations) * 1000:.2f}ms")
    print(f"  Stdev: {statistics.stdev(durations) * 1000:.2f}ms" if len(durations) > 1 else "  Stdev: N/A")
    
    if len(durations) >= 10:
        sorted_durations = sorted(durations)
        p50 = sorted_durations[int(len(sorted_durations) * 0.50)]
        p95 = sorted_durations[int(len(sorted_durations) * 0.95)]
        p99 = sorted_durations[int(len(sorted_durations) * 0.99)]
        print(f"  P50: {p50 * 1000:.2f}ms")
        print(f"  P95: {p95 * 1000:.2f}ms")
        print(f"  P99: {p99 * 1000:.2f}ms")


def main():
    """Run all benchmarks"""
    print("=" * 70)
    print("WOTR Platform Performance Benchmarks")
    print(f"Target: {API_URL}")
    print(f"Start time: {datetime.now().isoformat()}")
    print("=" * 70)
    
    # Check if service is available
    try:
        response = requests.get(f"{API_URL}/health", timeout=5)
        print(f"\n✓ Service is reachable (status: {response.status_code})")
    except Exception as e:
        print(f"\n✗ Error: Cannot reach service - {e}")
        print("Make sure the service is running: docker-compose up -d")
        return
    
    # Run benchmarks
    try:
        benchmark_health_endpoint(100)
        benchmark_metrics_endpoint(50)
        benchmark_ingest_endpoint(50)
        benchmark_concurrent_ingests(100, 10)
        benchmark_concurrent_ingests(200, 20)  # Higher concurrency
    except KeyboardInterrupt:
        print("\n\nBenchmark interrupted by user")
    except Exception as e:
        print(f"\n\nError during benchmark: {e}")
    
    print("\n" + "=" * 70)
    print(f"Benchmarks completed at {datetime.now().isoformat()}")
    print("=" * 70)


if __name__ == "__main__":
    main()
