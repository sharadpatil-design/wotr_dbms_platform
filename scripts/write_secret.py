s = 'http://test-receiver:5000/webhook\n'
with open('observability/secrets/webhook_url','wb') as f:
    f.write(s.encode('utf-8'))
print('wrote')
