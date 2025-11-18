import requests
import time
import sys
from pprint import pprint

FASTAPI_BASE = "http://localhost:8000"
PROM_BASE = "http://localhost:9090"
AM_BASE = "http://localhost:9093"

def log(msg):
    print(f"\n🟢 {msg}")
    print("-" * 60)

def wait_for_fastapi(timeout=60):
    log("Checking FastAPI health...")
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = requests.get(f"{FASTAPI_BASE}/health", timeout=5)
            print(f"Response: {r.status_code} {r.text}")
            if r.status_code == 200:
                print("✅ FastAPI Health OK")
                return True
        except Exception as e:
            print(f"⚠️  Health check failed: {e}")
        time.sleep(2)
    print("❌ FastAPI health check timed out")
    return False

def run_ingest():
    log("Testing FastAPI ingest endpoint...")
    payload = {"payload": {"example": "ci-debug", "value": 1}}
    try:
        r = requests.post(f"{FASTAPI_BASE}/ingest", json=payload, timeout=10)
        print(f"Response Code: {r.status_code}")
        print("Response Body:")
        print(r.text)
        if r.status_code == 200:
            print("✅ Ingest OK")
            return True
    except Exception as e:
        print(f"❌ Error during ingest: {e}")
    return False

def check_prometheus_rules(timeout=20):
    log("Checking Prometheus rule groups...")
    url = f"{PROM_BASE}/api/v1/rules"
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                groups = data.get("data", {}).get("groups", [])
                print(f"Rule Groups Found: {len(groups)}")
                if groups:
                    print("✅ Rules loaded successfully")
                    return True
            else:
                print(r.text)
        except Exception as e:
            print(f"⚠️  Error querying Prometheus rules: {e}")
        time.sleep(2)
    print("❌ No rule groups found in Prometheus")
    return False

def check_prometheus_alertmanagers(timeout=20):
    log("Checking Prometheus connection to Alertmanager...")
    url = f"{PROM_BASE}/api/v1/alertmanagers"
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                active = data.get("data", {}).get("activeAlertmanagers", [])
                print(f"Active Alertmanagers: {len(active)}")
                if active:
                    print("✅ Alertmanager linked correctly")
                    return True
                else:
                    print("⚠️  No active Alertmanagers found yet")
            else:
                print(r.text)
        except Exception as e:
            print(f"⚠️  Error checking alertmanagers: {e}")
        time.sleep(2)
    print("❌ Prometheus cannot reach Alertmanager")
    return False

def check_alertmanager_status(timeout=20):
    log("Checking Alertmanager API health...")
    url = f"{AM_BASE}/api/v2/status"
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                print("✅ Alertmanager API OK")
                return True
            else:
                print(f"⚠️  Non-200 response: {r.text}")
        except Exception as e:
            print(f"⚠️  Error querying Alertmanager: {e}")
        time.sleep(2)
    print("❌ Alertmanager /api/v2/status not reachable")
    return False

# 🚨 Simulate a mock FastAPI alert
def trigger_mock_alert():
    log("Triggering mock FastAPI alert...")

    # Step 1: Temporarily stop FastAPI
    print("🛑 Stopping FastAPI container to simulate outage...")
    import subprocess
    subprocess.run("docker stop fastapi", shell=True)

    print("⏳ Waiting 30s for Prometheus to detect outage...")
    time.sleep(30)

    # Step 2: Check active alerts in Prometheus
    print("📡 Checking for active alerts in Prometheus...")
    try:
        r = requests.get(f"{PROM_BASE}/api/v1/alerts", timeout=10)
        data = r.json()
        alerts = data.get("data", {}).get("alerts", [])
        if alerts:
            print(f"✅ {len(alerts)} alert(s) detected:")
            for alert in alerts:
                print(f"🔔 {alert.get('labels', {}).get('alertname')} - {alert.get('state')}")
            return True
        else:
            print("⚠️ No alerts detected yet.")
    except Exception as e:
        print(f"❌ Error querying alerts: {e}")

    # Step 3: Restart FastAPI
    print("♻️ Restarting FastAPI container...")
    subprocess.run("docker start fastapi", shell=True)
    return False

if __name__ == "__main__":
    print("🚀 Starting Debug Smoke Test with Alert Trigger...\n")

    if not wait_for_fastapi():
        sys.exit(2)

    if not run_ingest():
        sys.exit(3)

    if not check_prometheus_rules():
        sys.exit(4)

    if not check_prometheus_alertmanagers():
        sys.exit(5)

    if not check_alertmanager_status():
        sys.exit(6)

    # 🔥 Trigger mock alert to test pipeline
    alert_ok = trigger_mock_alert()
    if alert_ok:
        print("\n🎉 Mock Alert Successfully Triggered & Detected!")
    else:
        print("\n⚠️ Mock Alert Triggered, but not detected. Check Prometheus rule timing.")

    print("\n✅ Smoke Test Completed.")
