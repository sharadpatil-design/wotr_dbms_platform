import requests, json, time

url = "http://localhost:8000/ingest"
headers = {
    "Content-Type": "application/json",
    "X-API-Key": "dev-key-12345"  # Add API key for authentication
}
payload = {"payload": {"example": "hello", "value": 123}}

for i in range(1):
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=60)
        print("Status:", r.status_code, r.text)
    except Exception as e:
        print("Request failed:", e)
        time.sleep(2)
