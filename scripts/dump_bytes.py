p = 'observability/secrets/webhook_url'
with open(p,'rb') as f:
    b = f.read()
print(b)
print(list(b))
