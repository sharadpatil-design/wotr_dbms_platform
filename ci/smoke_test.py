import requests
import time
import sys

FASTAPI_BASE = "http://localhost:8000"
PROM_BASE = "http://localhost:9090"
AM_BASE = "http://localhost:9093"


def wait_for_fastapi(timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = requests.get(f"{FASTAPI_BASE}/health", timeout=5)
            if r.status_code == 200:
                print("FastAPI Health OK")
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def run_ingest():
    payload = {"payload": {"example": "ci-smoke", "value": 1}}
    r = requests.post(f"{FASTAPI_BASE}/ingest", json=payload, timeout=30)
    print("Ingest status:", r.status_code, r.text)
    return r.status_code == 200


def check_prometheus_rules(timeout=30):
    t0 = time.time()
    url = f"{PROM_BASE}/api/v1/rules"
    while time.time() - t0 < timeout:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                groups = data.get('data', {}).get('groups', [])
                print(f"Prometheus rule groups: {len(groups)}")
                return len(groups) > 0
        except Exception:
            pass
        time.sleep(2)
    return False


def check_prometheus_alertmanagers(timeout=30):
    t0 = time.time()
    url = f"{PROM_BASE}/api/v1/alertmanagers"
    while time.time() - t0 < timeout:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                active = data.get('data', {}).get('activeAlertmanagers', [])
                print(f"Active Alertmanagers: {len(active)}")
                return len(active) > 0
        except Exception:
            pass
        time.sleep(2)
    return False


def check_alertmanager_status(timeout=30):
    t0 = time.time()
    url = f"{AM_BASE}/api/v2/status"
    while time.time() - t0 < timeout:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                print("Alertmanager status OK")
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


if __name__ == '__main__':
    if not wait_for_fastapi(60):
        print("FastAPI health check failed")
        sys.exit(2)

    # Basic ingest smoke (now fatal: CI should fail if ingest doesn't work)
    ingest_ok = run_ingest()
    if not ingest_ok:
        print("Ingest endpoint returned error; failing smoke test")
        sys.exit(3)

    # Prometheus checks
    if not check_prometheus_rules(30):
        print("Prometheus rules not loaded or no rule groups found")
        sys.exit(4)
    if not check_prometheus_alertmanagers(30):
        print("Prometheus does not have an active Alertmanager")
        sys.exit(5)

    # Alertmanager check
    if not check_alertmanager_status(30):
        print("Alertmanager /api/v2/status not reachable")
        sys.exit(6)

    print("Smoke test passed")
    sys.exit(0)
