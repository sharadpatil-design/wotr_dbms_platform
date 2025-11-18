#!/bin/bash
# Generate self-signed SSL certificates for development
# For production, use Let's Encrypt or proper CA-signed certificates

set -e

CERT_DIR="$(dirname "$0")/../certs"
mkdir -p "$CERT_DIR"

echo "Generating self-signed SSL certificates..."
echo "⚠️  These are for DEVELOPMENT ONLY. Use proper certificates in production."

# Generate private key
openssl genrsa -out "$CERT_DIR/private.key" 2048

# Generate certificate signing request
openssl req -new -key "$CERT_DIR/private.key" -out "$CERT_DIR/cert.csr" \
    -subj "/C=US/ST=State/L=City/O=WOTR/CN=localhost"

# Generate self-signed certificate (valid for 365 days)
openssl x509 -req -days 365 -in "$CERT_DIR/cert.csr" \
    -signkey "$CERT_DIR/private.key" -out "$CERT_DIR/certificate.crt"

# Clean up CSR
rm "$CERT_DIR/cert.csr"

echo ""
echo "✓ SSL certificates generated:"
echo "  Private key: $CERT_DIR/private.key"
echo "  Certificate: $CERT_DIR/certificate.crt"
echo ""
echo "To use with uvicorn:"
echo "  uvicorn main:app --ssl-keyfile=$CERT_DIR/private.key --ssl-certfile=$CERT_DIR/certificate.crt"
