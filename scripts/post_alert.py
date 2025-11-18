import json
import sys
from urllib import request

with open('alerts.json','rb') as f:
    data = f.read()
req = request.Request('http://localhost:9093/api/v2/alerts', data=data, headers={'Content-Type':'application/json'}, method='POST')
try:
    with request.urlopen(req, timeout=10) as resp:
        print(resp.status)
        print(resp.read().decode())
except Exception as e:
    print('ERROR', e)
    sys.exit(1)
