# Test API Keys for Validation
# Add these to your .env file or export them

# Primary test API key (for validation testing)
export TEST_API_KEY="test-key-12345"

# Admin API key (for admin endpoints)
export ADMIN_API_KEY="admin-key-67890"

# Development API key
export DEV_API_KEY="dev-key-abcdef"

# Usage in tests:
# curl -H "X-API-Key: test-key-12345" http://localhost:8000/ingest -d '{"payload":{}}'
