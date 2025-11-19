# Data Pipeline Improvements

## Overview
Enhanced data pipeline with validation, schema evolution, dead letter queue (DLQ), and stream processing capabilities for production-grade data processing.

## 1. Data Validation & Quality Checks

### Schema Validation with Pydantic

**Location**: `services/api/app/schemas.py`

#### Supported Event Types
- `USER_ACTION` - User interactions
- `SYSTEM_EVENT` - System-generated events
- `API_CALL` - API request/response tracking
- `ERROR` - Error events
- `METRIC` - Metric data points

#### Validation Rules

**Required Fields**:
- `event_type`: Must be one of supported types
- `source`: Event source identifier (1-100 chars)

**Optional Fields with Validation**:
- `user_id`: Max 50 characters
- `session_id`: Max 100 characters
- `ip_address`: Valid IPv4 format
- `data`: Custom JSON object (max 100KB)
- `tags`: Array of strings (max 10 tags, alphanumeric only)
- `version`: Semantic version format (e.g., "1.0")

#### Example Valid Payload

```json
{
  "id": "evt_123456",
  "timestamp": "2025-11-19T10:30:00Z",
  "payload": {
    "event_type": "user_action",
    "source": "web_app",
    "user_id": "user123",
    "session_id": "sess456",
    "ip_address": "192.168.1.1",
    "data": {
      "action": "click",
      "element": "submit_button",
      "page": "/checkout"
    },
    "tags": ["frontend", "conversion"],
    "version": "1.0"
  }
}
```

### Validation Endpoint

Test validation before ingesting:

```bash
curl -X POST http://localhost:8000/validate \
  -H 'Content-Type: application/json' \
  -d '{
    "event_type": "user_action",
    "source": "web_app",
    "data": {"action": "click"}
  }'
```

Response:
```json
{
  "valid": true,
  "errors": [],
  "warnings": ["User action events should include user_id"]
}
```

### Data Quality Metrics

**Completeness Score**: 0.0 to 1.0 based on field coverage

```python
from schemas import DataQualityCheck

score = DataQualityCheck.check_completeness(payload)
# score = 1.0 (all fields present)
# score = 0.4 (only required fields)
```

**Freshness Check**: Validate event is not stale

```python
is_fresh = DataQualityCheck.check_freshness(
    timestamp_str="2025-11-19T10:30:00Z",
    max_age_seconds=3600  # 1 hour
)
```

**Consistency Check**: Business rule validation

```python
issues = DataQualityCheck.check_consistency(payload)
# Returns list of consistency issues
```

## 2. Schema Evolution with Avro

### Schema Registry

**Location**: `services/api/app/schema_evolution.py`

Manages multiple schema versions with backward/forward compatibility checks.

#### Registered Schemas

**Version 1.0** (Original):
- Basic fields: id, timestamp, payload
- Payload: event_type, source, data

**Version 2.0** (Extended):
- All v1.0 fields (backward compatible)
- Added: user_id, session_id, tags (all optional with defaults)

#### Usage

```python
from schema_evolution import get_schema_registry, AvroSerializer, SchemaEvolution

# Get schema registry
registry = get_schema_registry()

# Get specific version
schema_v1 = registry.get_schema("IngestEvent", version=1)
schema_v2 = registry.get_schema("IngestEvent", version=2)

# Check compatibility
is_backward_compat = SchemaEvolution.is_backward_compatible(schema_v1, schema_v2)
is_forward_compat = SchemaEvolution.is_forward_compatible(schema_v1, schema_v2)

# Serialize/deserialize
serializer = AvroSerializer(registry)
binary_data = serializer.serialize(event_data, "IngestEvent", version=2)
deserialized = serializer.deserialize(binary_data, "IngestEvent", writer_version=2)
```

#### Adding New Schema Version

```python
new_schema = {
    "type": "record",
    "name": "IngestEvent",
    "namespace": "com.wotr.events",
    "fields": [
        {"name": "id", "type": "string"},
        {"name": "new_field", "type": ["null", "string"], "default": None}  # Optional!
    ]
}

registry.register_schema("IngestEvent", version=3, schema_dict=new_schema)
```

### Compatibility Guidelines

**Backward Compatibility** (new schema reads old data):
- ✅ Add optional fields with defaults
- ✅ Add fields with null union type
- ❌ Remove fields
- ❌ Add required fields without defaults

**Forward Compatibility** (old schema reads new data):
- ✅ Add optional fields (ignored by old schema)
- ❌ Remove fields
- ❌ Change field types

## 3. Dead Letter Queue (DLQ)

### Architecture

**Location**: `services/consumer/dead_letter_queue.py`

Failed messages are:
1. Retried with exponential backoff (default: 3 attempts)
2. Sent to DLQ after exhausting retries
3. Stored in MinIO bucket `dead-letters`
4. Published to Kafka topic `dlq-events`

### Retry Strategy

```
Attempt 1: Immediate
Attempt 2: 2s delay
Attempt 3: 4s delay
Attempt 4: 8s delay
→ Send to DLQ
```

### DLQ Message Format

```json
{
  "dlq_id": "dlq_1700318400123_evt_123",
  "original_message": { ... },
  "error": {
    "type": "ValueError",
    "message": "Schema validation failed",
    "traceback": "..."
  },
  "retry_count": 3,
  "failed_at": "2025-11-19T10:30:00Z",
  "metadata": {
    "partition": 0,
    "offset": 12345
  }
}
```

### DLQ Storage

**MinIO Path Structure**:
```
dead-letters/
  failed/
    2025/
      11/
        19/
          dlq_1700318400123_evt_123.json
          dlq_1700318400456_evt_456.json
```

### DLQ Metrics

```promql
# Total DLQ messages by error type
dlq_messages_total{error_type="ValueError"}

# Retry attempts
dlq_retry_attempts_total

# Current DLQ backlog
dlq_backlog_size
```

### Processing DLQ Messages

```python
# List DLQ messages
from minio import Minio

minio = Minio("localhost:9000", ...)
objects = minio.list_objects("dead-letters", prefix="failed/", recursive=True)

for obj in objects:
    data = minio.get_object("dead-letters", obj.object_name)
    dlq_message = json.loads(data.read())
    
    # Inspect and fix original message
    original = dlq_message["original_message"]
    error = dlq_message["error"]
    
    # Re-submit after fixing
    # POST /ingest with corrected data
```

### Configuration

```bash
# docker-compose.yml
MAX_RETRIES=3  # Maximum retry attempts
KAFKA_DLQ_TOPIC=dlq-events  # DLQ topic name
```

## 4. Stream Processing

### Components

**Location**: `services/consumer/stream_processing.py`

#### Time Windows

**Tumbling Window** (non-overlapping):
```python
from stream_processing import TimeWindow

window = TimeWindow(duration_seconds=60)  # 1-minute window
window.add_event(event, timestamp)

if window.is_ready(current_time, last_trigger):
    events = window.get_events()
    # Process window
```

**Sliding Window** (overlapping):
```python
window = TimeWindow(duration_seconds=60, slide_seconds=30)  # 1-min window, 30s slide
```

#### Session Windows

Group events by session with timeout:

```python
from stream_processing import SessionWindow

session_window = SessionWindow(session_timeout_seconds=300)  # 5-minute timeout
session_window.add_event(event, session_id="sess123", timestamp=time.time())

# Get session data
session = session_window.get_session("sess123")
print(f"Events in session: {len(session['events'])}")
```

#### Aggregations

```python
from stream_processing import StreamAggregator

aggregator = StreamAggregator()

# Count by key
aggregator.count("event_type:user_action")

# Sum values
aggregator.sum("revenue", 99.99)

# Group counts
aggregator.group_count("by_event_type", "user_action")

# Get top K
top_sources = aggregator.top_k("by_source", k=10)
```

#### Stream Joins

Join two streams within time window:

```python
from stream_processing import StreamJoiner

joiner = StreamJoiner(join_window_seconds=60)

# Add events from different streams
joiner.add_left(key="user123", event=event1, timestamp=t1)
joiner.add_right(key="user123", event=event2, timestamp=t2)

# Get joined events
joined = joiner.get_joined_events()
for j in joined:
    print(f"Left: {j['left']}, Right: {j['right']}, Time diff: {j['time_diff']}s")
```

### Stream Processing Example

```python
from stream_processing import StreamProcessor

processor = StreamProcessor(window_duration=60)

# Process events as they arrive
for event in kafka_consumer:
    processor.process_event(event.value)
    
    # Get current stats
    stats = processor.get_stats()
    print(f"Window size: {stats['window_count']}")
    print(f"Active sessions: {stats['active_sessions']}")
    print(f"Top sources: {stats['top_sources']}")
```

## 5. Enhanced Consumer

### Features

**Location**: `services/consumer/consumer_with_dlq.py`

- ✅ Schema validation before processing
- ✅ Automatic retry with exponential backoff
- ✅ Dead letter queue for failed messages
- ✅ Enhanced ClickHouse schema with validation status
- ✅ Comprehensive metrics and logging

### ClickHouse Schema

```sql
CREATE TABLE wotr.ingested_data (
    id String,
    timestamp String,
    payload String,
    event_type String,          -- NEW: Extracted for fast filtering
    source String,              -- NEW: Extracted for aggregations
    validation_status String,   -- NEW: "valid" or "failed"
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (event_type, created_at, id)  -- Optimized for queries
PARTITION BY toYYYYMM(created_at);     -- Monthly partitions
```

### Metrics

```promql
# Validation failures
consumer_validation_failures_total{reason="schema_error"}

# Messages processed by status
consumer_messages_processed_total{status="success"}
consumer_messages_processed_total{status="retried"}
consumer_messages_processed_total{status="dlq"}

# Processing latency (p95)
histogram_quantile(0.95, consumer_processing_duration_seconds_bucket)
```

## Configuration

### Environment Variables

```bash
# FastAPI Service
VALIDATION_ENABLED=true
DATA_QUALITY_MIN_SCORE=0.5
SCHEMA_VERSION=2

# Consumer Service
MAX_RETRIES=3
KAFKA_DLQ_TOPIC=dlq-events
MINIO_ENDPOINT=minio:9000
VALIDATION_MODE=strict  # strict, warn, or disabled
```

## Testing

### Test Validation

```bash
# Valid payload
curl -X POST http://localhost:8000/ingest \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: dev-key-12345' \
  -d '{
    "payload": {
      "event_type": "user_action",
      "source": "web_app",
      "user_id": "user123",
      "data": {"action": "click"}
    }
  }'

# Invalid payload (missing required field)
curl -X POST http://localhost:8000/ingest \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: dev-key-12345' \
  -d '{
    "payload": {
      "source": "web_app"
    }
  }'
# Expected: 422 Validation Error
```

### Test DLQ

```bash
# Cause a processing error (invalid ClickHouse connection)
docker-compose stop clickhouse

# Send events - they should retry then go to DLQ
curl -X POST http://localhost:8000/ingest \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: dev-key-12345' \
  -d '{...}'

# Check DLQ metrics
curl http://localhost:8001/metrics | grep dlq

# Inspect DLQ bucket
docker exec -it wotr_dbms_platform-minio-1 mc ls local/dead-letters/failed/
```

## Best Practices

### Schema Design

1. **Always make new fields optional** with defaults for backward compatibility
2. **Never remove fields** from schemas without major version bump
3. **Use semantic versioning** for schema versions
4. **Document breaking changes** clearly

### Validation

1. **Validate early** at API entry point before Kafka
2. **Log validation failures** with detailed error messages
3. **Monitor validation failure rate** - spike indicates client issues
4. **Provide validation endpoint** for clients to test payloads

### DLQ Management

1. **Monitor DLQ size** - growing DLQ indicates systematic issues
2. **Set up alerts** for DLQ message rate
3. **Review DLQ messages** regularly to identify patterns
4. **Implement DLQ replay** mechanism for recovered messages
5. **Archive old DLQ messages** after investigation

### Stream Processing

1. **Choose appropriate window size** based on data volume and latency requirements
2. **Monitor window lag** - growing lag indicates processing bottleneck
3. **Use session windows** for user journey analysis
4. **Implement watermarks** for handling late-arriving data
5. **Consider stateful processing** for complex aggregations

## Troubleshooting

### High Validation Failure Rate

```bash
# Check validation metrics
curl http://localhost:8000/metrics | grep validation_failures

# View recent validation errors
docker logs fastapi | grep "Validation failed"
```

### DLQ Growing

```bash
# Check DLQ metrics
curl http://localhost:8001/metrics | grep dlq_messages_total

# Inspect DLQ messages
# Connect to MinIO UI: http://localhost:9000
# Browse dead-letters bucket
```

### Schema Evolution Issues

```bash
# Test schema compatibility
python -c "
from schema_evolution import get_schema_registry, SchemaEvolution
registry = get_schema_registry()
v1 = registry.get_schema('IngestEvent', 1)
v2 = registry.get_schema('IngestEvent', 2)
print('Backward compatible:', SchemaEvolution.is_backward_compatible(v1, v2))
print('Forward compatible:', SchemaEvolution.is_forward_compatible(v1, v2))
"
```

## Performance Considerations

- **Validation overhead**: ~1-2ms per event
- **Avro serialization**: 50-70% size reduction vs JSON
- **DLQ storage**: MinIO provides S3-compatible object storage
- **Stream processing**: In-memory windows, consider Redis for distributed deployment

## References

- [Pydantic Documentation](https://docs.pydantic.dev/)
- [Apache Avro](https://avro.apache.org/docs/current/)
- [Stream Processing Patterns](https://www.confluent.io/blog/stream-processing-part-1-tutorial-developing-streaming-applications/)
- [Dead Letter Queue Pattern](https://aws.amazon.com/what-is/dead-letter-queue/)
