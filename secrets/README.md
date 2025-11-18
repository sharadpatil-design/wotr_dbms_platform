# Secrets Management Configuration

This directory contains guidance for managing secrets securely.

## ⚠️ NEVER COMMIT ACTUAL SECRETS TO GIT

## Development Secrets

For local development, use `.env` file (add to `.gitignore`):

```bash
# .env (DO NOT COMMIT)
API_KEYS=dev-key-12345,test-key-67890
POSTGRES_PASSWORD=secure_password_here
CLICKHOUSE_PASSWORD=another_secure_password
MINIO_SECRET_KEY=minio_secret_key_here
KAFKA_SASL_PASSWORD=kafka_password_here
```

Load with:
```bash
docker-compose --env-file .env up
```

## Production Secrets Management Options

### Option 1: Docker Secrets (Docker Swarm)

```bash
# Create secrets
echo "my_secure_password" | docker secret create postgres_password -
echo "api_key_xyz123" | docker secret create api_key -

# Use in docker-compose.yml
secrets:
  postgres_password:
    external: true
  api_key:
    external: true

services:
  fastapi:
    secrets:
      - postgres_password
      - api_key
```

### Option 2: HashiCorp Vault

```python
# Example: Fetch secrets from Vault
import hvac

client = hvac.Client(url='http://vault:8200', token=os.getenv('VAULT_TOKEN'))
secret = client.secrets.kv.v2.read_secret_version(path='wotr/api')
api_key = secret['data']['data']['api_key']
```

### Option 3: AWS Secrets Manager

```python
import boto3
from botocore.exceptions import ClientError

def get_secret(secret_name):
    client = boto3.client('secretsmanager', region_name='us-east-1')
    try:
        response = client.get_secret_value(SecretId=secret_name)
        return response['SecretString']
    except ClientError as e:
        raise e
```

### Option 4: Azure Key Vault

```python
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential

credential = DefaultAzureCredential()
client = SecretClient(vault_url="https://wotr-vault.vault.azure.net/", credential=credential)
secret = client.get_secret("api-key")
```

### Option 5: Kubernetes Secrets

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: wotr-secrets
type: Opaque
stringData:
  api-key: "your-api-key-here"
  postgres-password: "your-postgres-password"
```

## Secret Rotation

### Automated Rotation Strategy

1. **API Keys**: Rotate every 90 days
2. **Database Passwords**: Rotate every 180 days
3. **Service-to-Service Credentials**: Rotate every 30 days

### Rotation Script Example

```bash
#!/bin/bash
# rotate_secrets.sh

NEW_API_KEY=$(openssl rand -hex 32)
NEW_PASSWORD=$(openssl rand -base64 32)

# Update in secrets manager
aws secretsmanager update-secret --secret-id wotr/api-key --secret-string "$NEW_API_KEY"

# Trigger rolling restart of services
docker-compose restart fastapi
```

## Encryption at Rest

### Encrypt sensitive files

```bash
# Encrypt
openssl enc -aes-256-cbc -salt -in secrets.txt -out secrets.txt.enc

# Decrypt
openssl enc -d -aes-256-cbc -in secrets.txt.enc -out secrets.txt
```

### Use git-crypt for repository encryption

```bash
git-crypt init
echo "secrets/*.key filter=git-crypt diff=git-crypt" >> .gitattributes
git-crypt add-gpg-user <gpg-key-id>
```

## Environment-Specific Secrets

```
secrets/
├── dev/
│   ├── .env
│   └── api-keys.txt
├── staging/
│   ├── .env
│   └── api-keys.txt
└── production/
    ├── .env (encrypted)
    └── api-keys.txt (encrypted)
```

## Auditing

Track secret access and rotation:

```python
import logging
from datetime import datetime

def log_secret_access(secret_name, action):
    logging.info(f"[AUDIT] {datetime.utcnow().isoformat()} - {action} - {secret_name}")
```

## Checklist for Production

- [ ] All secrets removed from code and config files
- [ ] Secrets stored in dedicated secrets manager
- [ ] Access controls configured (least privilege)
- [ ] Automatic rotation enabled
- [ ] Audit logging configured
- [ ] Encryption at rest enabled
- [ ] Backup and recovery procedures documented
- [ ] Emergency access procedures defined
- [ ] Regular security audits scheduled
