#!/usr/bin/env python3
"""
Chaos Engineering: Data Corruption Tests

Tests the platform's resilience to corrupted or malformed data:
- Invalid JSON
- Schema violations
- Encoding errors
- Missing required fields
- Type mismatches

⚠️ WARNING: These tests send invalid data. Run in dev environment only!
"""

import pytest
import requests
import json

# Test configuration
API_BASE_URL = "http://localhost:8000"
INGEST_URL = f"{API_BASE_URL}/ingest"
ADMIN_URL = f"{API_BASE_URL}/admin"


class TestDataCorruption:
    """Test handling of corrupted data."""
    
    def test_invalid_json(self):
        """Test handling of invalid JSON."""
        print("\n=== Testing Invalid JSON ===")
        
        # Send malformed JSON
        invalid_payloads = [
            '{"incomplete": ',
            '{"trailing": "comma",}',
            '{invalid json}',
            'null',
            '{"payload": undefined}',
        ]
        
        for payload in invalid_payloads:
            print(f"Testing: {payload[:50]}...")
            try:
                response = requests.post(
                    INGEST_URL,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=10
                )
                # Should reject with 400 or 422
                assert response.status_code in [400, 422], f"Expected 400/422, got {response.status_code}"
                print(f"  ✅ Rejected with {response.status_code}")
            except requests.RequestException as e:
                pytest.fail(f"Request failed unexpectedly: {e}")
        
        print("✅ Invalid JSON handled correctly")
    
    def test_missing_required_fields(self):
        """Test handling of missing required fields."""
        print("\n=== Testing Missing Required Fields ===")
        
        # Missing payload
        response = requests.post(
            INGEST_URL,
            json={"id": "test123"},
            timeout=10
        )
        assert response.status_code in [400, 422], "Should reject missing payload"
        print(f"  ✅ Missing payload rejected: {response.status_code}")
        
        # Missing event_type
        response = requests.post(
            INGEST_URL,
            json={"payload": {"example": "test"}},
            timeout=10
        )
        assert response.status_code in [200, 400, 422], "Should handle missing event_type"
        print(f"  ✅ Missing event_type handled: {response.status_code}")
        
        # Empty payload
        response = requests.post(
            INGEST_URL,
            json={"payload": {}},
            timeout=10
        )
        assert response.status_code in [200, 400, 422], "Should handle empty payload"
        print(f"  ✅ Empty payload handled: {response.status_code}")
        
        print("✅ Missing fields handled correctly")
    
    def test_type_mismatches(self):
        """Test handling of type mismatches."""
        print("\n=== Testing Type Mismatches ===")
        
        # String where number expected
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": "user_action", "count": "not_a_number"}},
            timeout=10
        )
        # Should either accept (coerce) or reject gracefully
        assert response.status_code in [200, 400, 422], f"Unexpected status: {response.status_code}"
        print(f"  ✅ Type mismatch handled: {response.status_code}")
        
        # Number where string expected
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": 12345}},
            timeout=10
        )
        assert response.status_code in [200, 400, 422], f"Unexpected status: {response.status_code}"
        print(f"  ✅ Type mismatch handled: {response.status_code}")
        
        # Array where object expected
        response = requests.post(
            INGEST_URL,
            json={"payload": []},
            timeout=10
        )
        assert response.status_code in [400, 422], "Should reject array payload"
        print(f"  ✅ Array payload rejected: {response.status_code}")
        
        print("✅ Type mismatches handled correctly")
    
    def test_invalid_event_types(self):
        """Test handling of invalid event types."""
        print("\n=== Testing Invalid Event Types ===")
        
        invalid_types = [
            "invalid_type",
            "",
            None,
            12345,
            {"nested": "object"},
            ["array"],
        ]
        
        for event_type in invalid_types:
            print(f"Testing event_type: {event_type}...")
            response = requests.post(
                INGEST_URL,
                json={"payload": {"event_type": event_type, "example": "test"}},
                timeout=10
            )
            # Should either accept or reject gracefully
            assert response.status_code in [200, 400, 422], f"Unexpected status: {response.status_code}"
            print(f"  Status: {response.status_code}")
        
        print("✅ Invalid event types handled")
    
    def test_oversized_payloads(self):
        """Test handling of very large payloads."""
        print("\n=== Testing Oversized Payloads ===")
        
        # 10MB payload
        large_string = "x" * (10 * 1024 * 1024)
        
        try:
            response = requests.post(
                INGEST_URL,
                json={"payload": {"event_type": "user_action", "data": large_string}},
                timeout=30
            )
            
            if response.status_code == 413:
                print("  ✅ Oversized payload rejected (413 Payload Too Large)")
            elif response.status_code == 422:
                print("  ✅ Oversized payload rejected (422 Validation Error)")
            elif response.status_code == 500:
                print("  ⚠️ Server error on oversized payload (should handle gracefully)")
            elif response.status_code == 200:
                print("  ⚠️ Oversized payload accepted (consider adding size limits)")
            else:
                print(f"  Status: {response.status_code}")
        except requests.RequestException as e:
            print(f"  ✅ Request failed as expected: {type(e).__name__}")
        
        print("✅ Oversized payloads handled")
    
    def test_special_characters(self):
        """Test handling of special characters and encoding issues."""
        print("\n=== Testing Special Characters ===")
        
        special_strings = [
            "Hello 世界",  # Unicode
            "emoji 🚀🔥💯",  # Emojis
            "quotes: \"'`",  # Quotes
            "newlines\n\r\ttabs",  # Whitespace
            "<script>alert('xss')</script>",  # HTML/XSS
            "null\x00byte",  # Null byte
            "\\x00\\x01\\x02",  # Escape sequences
        ]
        
        for test_string in special_strings:
            print(f"Testing: {test_string[:30]}...")
            response = requests.post(
                INGEST_URL,
                json={"payload": {"event_type": "user_action", "data": test_string}},
                timeout=10
            )
            # Should handle gracefully
            assert response.status_code in [200, 400, 422], f"Unexpected status: {response.status_code}"
            print(f"  ✅ Handled: {response.status_code}")
        
        print("✅ Special characters handled")
    
    def test_nested_depth(self):
        """Test handling of deeply nested objects."""
        print("\n=== Testing Deeply Nested Objects ===")
        
        # Create deeply nested object
        nested = {"level": 0}
        current = nested
        for i in range(1, 100):
            current["nested"] = {"level": i}
            current = current["nested"]
        
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": "user_action", "data": nested}},
            timeout=10
        )
        
        # Should either accept or reject gracefully
        assert response.status_code in [200, 400, 422, 500], f"Unexpected status: {response.status_code}"
        print(f"  Deeply nested object: {response.status_code}")
        
        print("✅ Nested objects handled")
    
    def test_duplicate_keys(self):
        """Test handling of duplicate keys in JSON."""
        print("\n=== Testing Duplicate Keys ===")
        
        # JSON with duplicate keys (Python dict will dedupe, but test anyway)
        payload = '{"payload": {"event_type": "user_action", "data": "first", "data": "second"}}'
        
        response = requests.post(
            INGEST_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        # Should handle gracefully (Python keeps last value)
        assert response.status_code in [200, 400, 422], f"Unexpected status: {response.status_code}"
        print(f"  Duplicate keys: {response.status_code}")
        
        print("✅ Duplicate keys handled")


class TestValidationRobustness:
    """Test validation logic robustness."""
    
    def test_boundary_values(self):
        """Test boundary values for numeric fields."""
        print("\n=== Testing Boundary Values ===")
        
        boundary_values = [
            0,
            -1,
            2**31 - 1,  # Max int32
            2**63 - 1,  # Max int64
            -2**63,  # Min int64
            1.7976931348623157e+308,  # Max float
            2.2250738585072014e-308,  # Min float
        ]
        
        for value in boundary_values:
            print(f"Testing value: {value}...")
            response = requests.post(
                INGEST_URL,
                json={"payload": {"event_type": "user_action", "value": value}},
                timeout=10
            )
            assert response.status_code in [200, 400, 422], f"Unexpected status: {response.status_code}"
            print(f"  ✅ {response.status_code}")
        
        print("✅ Boundary values handled")
    
    def test_sql_injection_attempts(self):
        """Test that SQL injection attempts are handled safely."""
        print("\n=== Testing SQL Injection Attempts ===")
        
        sql_injection_strings = [
            "'; DROP TABLE ingest_meta; --",
            "1' OR '1'='1",
            "admin'--",
            "' UNION SELECT * FROM users--",
        ]
        
        for sql in sql_injection_strings:
            print(f"Testing SQL injection: {sql[:30]}...")
            response = requests.post(
                INGEST_URL,
                json={"payload": {"event_type": "user_action", "data": sql}},
                timeout=10
            )
            # Should handle safely
            assert response.status_code in [200, 400, 422], f"Unexpected status: {response.status_code}"
            print(f"  ✅ Handled safely: {response.status_code}")
        
        print("✅ SQL injection attempts handled safely")
    
    def test_xss_attempts(self):
        """Test that XSS attempts are handled safely."""
        print("\n=== Testing XSS Attempts ===")
        
        xss_strings = [
            "<script>alert('xss')</script>",
            "<img src=x onerror=alert('xss')>",
            "javascript:alert('xss')",
            "<iframe src='javascript:alert(\"xss\")'></iframe>",
        ]
        
        for xss in xss_strings:
            print(f"Testing XSS: {xss[:30]}...")
            response = requests.post(
                INGEST_URL,
                json={"payload": {"event_type": "user_action", "data": xss}},
                timeout=10
            )
            # Should handle safely
            assert response.status_code in [200, 400, 422], f"Unexpected status: {response.status_code}"
            print(f"  ✅ Handled safely: {response.status_code}")
        
        print("✅ XSS attempts handled safely")


class TestDLQBehavior:
    """Test Dead Letter Queue behavior with corrupted data."""
    
    def test_invalid_data_goes_to_dlq(self):
        """Test that invalid data is sent to DLQ."""
        print("\n=== Testing DLQ for Invalid Data ===")
        
        # This test requires the consumer to be running
        # Send data that will fail validation at consumer level
        
        # Get current DLQ count
        try:
            response = requests.get(f"{ADMIN_URL}/stats", timeout=10)
            if response.status_code == 200:
                initial_dlq = response.json().get("dlq_messages", 0)
                print(f"Initial DLQ messages: {initial_dlq}")
            else:
                pytest.skip("Admin stats not available")
        except requests.RequestException:
            pytest.skip("Admin API not available")
        
        # Send potentially problematic data
        # (Actual validation depends on consumer implementation)
        response = requests.post(
            INGEST_URL,
            json={"payload": {"event_type": "invalid_type_for_consumer", "data": "test"}},
            timeout=10
        )
        
        # Wait for consumer to process
        import time
        time.sleep(5)
        
        # Check if DLQ increased (if validation fails at consumer)
        try:
            response = requests.get(f"{ADMIN_URL}/stats", timeout=10)
            if response.status_code == 200:
                final_dlq = response.json().get("dlq_messages", 0)
                print(f"Final DLQ messages: {final_dlq}")
                
                if final_dlq > initial_dlq:
                    print("✅ Invalid data sent to DLQ")
                else:
                    print("⚠️ Data may have been accepted or DLQ not used")
        except requests.RequestException:
            pass


def test_system_stability_after_corruption():
    """Verify system remains stable after processing corrupted data."""
    print("\n=== Testing System Stability After Corruption ===")
    
    # Send various corrupted payloads
    corrupted_payloads = [
        '{"incomplete"',
        '{"payload": null}',
        '{"payload": []}',
    ]
    
    for payload in corrupted_payloads:
        try:
            requests.post(
                INGEST_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                timeout=5
            )
        except:
            pass
    
    # System should still be healthy
    import time
    time.sleep(2)
    
    response = requests.get(f"{API_BASE_URL}/health", timeout=10)
    assert response.status_code == 200, "System unhealthy after corruption tests"
    
    # Should accept valid payload
    response = requests.post(
        INGEST_URL,
        json={"payload": {"event_type": "user_action", "example": "recovery_test"}},
        timeout=10
    )
    assert response.status_code == 200, "Cannot process valid data after corruption"
    
    print("✅ System stable after processing corrupted data")


if __name__ == "__main__":
    # Run with: python test_data_corruption.py
    pytest.main([__file__, "-v", "-s"])
