import json
import os
import time
import sys
import requests

# Configurable via environment for CI
AM_URL = os.environ.get('ALERTMANAGER_URL', 'http://localhost:9093/api/v2/alerts')
RECEIVER_LAST = os.environ.get('RECEIVER_LAST', 'http://localhost:5000/last')
ROUTE_TIMEOUT = int(os.environ.get('ALERT_ROUTE_TIMEOUT', '60'))
DELIVERY_TIMEOUT = int(os.environ.get('ALERT_DELIVERY_TIMEOUT', '120'))


def post_alert():
    payload = [
        {
            "labels": {"alertname": "TestNotification", "severity": "critical"},
            "annotations": {"summary": "ci-test-delivery"},
            "startsAt": "2025-11-07T00:00:00Z"
        }
    ]
    r = requests.post(AM_URL, json=payload, timeout=10)
    print('Post alerts status', r.status_code, r.text)
    return r.status_code in (200, 202)


def wait_for_alertmanager_route(timeout=ROUTE_TIMEOUT):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = requests.get(AM_URL, timeout=5)
            if r.status_code == 200:
                data = r.json()
                for item in data:
                    # r.json() for /api/v2/alerts returns a list
                    pass
                # Older Alertmanager API returns a list of alerts; check entries
                if isinstance(data, list):
                    for a in data:
                        receivers = a.get('receivers', [])
                        for recv in receivers:
                            if recv.get('name') == 'webhook-test':
                                print('Alertmanager has routed alert to webhook-test')
                                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def wait_for_delivery(timeout=DELIVERY_TIMEOUT):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = requests.get(RECEIVER_LAST, timeout=5)
            if r.status_code == 200 and 'TestNotification' in r.text:
                print('Delivery observed at test-receiver')
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


if __name__ == '__main__':
    if not post_alert():
        print('Failed to post alert to Alertmanager')
        sys.exit(2)

    # First ensure Alertmanager has a routed alert for webhook-test
    if not wait_for_alertmanager_route():
        print('Alertmanager did not route alert to webhook-test within timeout')
        sys.exit(3)

    # Then wait for the receiver to observe delivery
    if not wait_for_delivery():
        print('Alert not delivered to test-receiver within timeout')
        sys.exit(4)

    print('Alert delivery confirmed')
    sys.exit(0)
