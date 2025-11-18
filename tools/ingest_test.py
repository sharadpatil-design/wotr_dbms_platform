import requests, json, time
url = "http://localhost:8000/ingest"
payload = {"payload": {"example": "hello", "value": 123}}
for i in range(1):
    try:
        r = requests.post(url, json=payload, timeout=60)
        print("Status:", r.status_code, r.text)
    except Exception as e:
        print("Request failed:", e)
        time.sleep(2)
