"""
Data validation schemas and quality checks
"""
from pydantic import BaseModel, Field, field_validator, ValidationError
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum
import json


class EventType(str, Enum):
    """Supported event types"""
    USER_ACTION = "user_action"
    SYSTEM_EVENT = "system_event"
    API_CALL = "api_call"
    ERROR = "error"
    METRIC = "metric"


class PayloadSchema(BaseModel):
    """Base schema for event payloads with validation"""
    
    # Required fields
    event_type: EventType = Field(..., description="Type of event")
    source: str = Field(..., min_length=1, max_length=100, description="Event source")
    
    # Optional fields with defaults
    user_id: Optional[str] = Field(None, max_length=50)
    session_id: Optional[str] = Field(None, max_length=100)
    ip_address: Optional[str] = Field(None, pattern=r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$')
    
    # Custom data
    data: Dict[str, Any] = Field(default_factory=dict, description="Custom event data")
    tags: List[str] = Field(default_factory=list, max_length=10, description="Event tags")
    
    # Metadata
    version: str = Field(default="1.0", pattern=r'^\d+\.\d+$')
    
    @field_validator('data')
    @classmethod
    def validate_data_size(cls, v):
        """Ensure data payload is not too large"""
        data_str = json.dumps(v)
        if len(data_str) > 100_000:  # 100KB limit
            raise ValueError("Data payload exceeds 100KB limit")
        return v
    
    @field_validator('tags')
    @classmethod
    def validate_tags(cls, v):
        """Ensure tags are alphanumeric"""
        for tag in v:
            if not tag.replace('_', '').replace('-', '').isalnum():
                raise ValueError(f"Tag '{tag}' contains invalid characters")
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "event_type": "user_action",
                "source": "web_app",
                "user_id": "user123",
                "session_id": "sess456",
                "data": {
                    "action": "click",
                    "element": "submit_button",
                    "page": "/checkout"
                },
                "tags": ["frontend", "conversion"],
                "version": "1.0"
            }
        }


class IngestRequest(BaseModel):
    """Enhanced ingest request with validation"""
    id: Optional[str] = Field(None, max_length=100)
    timestamp: Optional[str] = Field(None)
    payload: PayloadSchema
    
    @field_validator('timestamp')
    @classmethod
    def validate_timestamp(cls, v):
        """Ensure timestamp is valid ISO format"""
        if v:
            try:
                datetime.fromisoformat(v.replace('Z', '+00:00'))
            except ValueError:
                raise ValueError("Timestamp must be in ISO 8601 format")
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "evt_123456",
                "timestamp": "2025-11-19T10:30:00Z",
                "payload": PayloadSchema.Config.json_schema_extra["example"]
            }
        }


class ValidationResult(BaseModel):
    """Result of validation check"""
    valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    
    def add_error(self, error: str):
        self.valid = False
        self.errors.append(error)
    
    def add_warning(self, warning: str):
        self.warnings.append(warning)


def validate_payload(data: Dict[str, Any]) -> ValidationResult:
    """
    Validate incoming payload data
    
    Args:
        data: Raw payload data
    
    Returns:
        ValidationResult with validation status
    """
    result = ValidationResult(valid=True)
    
    try:
        # Attempt to parse with Pydantic
        payload = PayloadSchema(**data)
        
        # Additional business logic checks
        if payload.event_type == EventType.ERROR and not payload.data.get('error_message'):
            result.add_warning("Error events should include error_message in data")
        
        if payload.event_type == EventType.USER_ACTION and not payload.user_id:
            result.add_warning("User action events should include user_id")
        
        # Check for required data fields based on event type
        if payload.event_type == EventType.METRIC:
            if 'metric_name' not in payload.data or 'metric_value' not in payload.data:
                result.add_error("Metric events must include metric_name and metric_value")
        
    except ValidationError as e:
        result.valid = False
        for error in e.errors():
            field = '.'.join(str(loc) for loc in error['loc'])
            result.add_error(f"{field}: {error['msg']}")
    
    return result


def create_avro_schema() -> str:
    """
    Generate Avro schema for event payloads
    
    Returns:
        Avro schema as JSON string
    """
    schema = {
        "type": "record",
        "name": "IngestEvent",
        "namespace": "com.wotr.events",
        "fields": [
            {"name": "id", "type": "string"},
            {"name": "timestamp", "type": "string"},
            {
                "name": "payload",
                "type": {
                    "type": "record",
                    "name": "Payload",
                    "fields": [
                        {"name": "event_type", "type": {"type": "enum", "name": "EventType", 
                         "symbols": ["USER_ACTION", "SYSTEM_EVENT", "API_CALL", "ERROR", "METRIC"]}},
                        {"name": "source", "type": "string"},
                        {"name": "user_id", "type": ["null", "string"], "default": None},
                        {"name": "session_id", "type": ["null", "string"], "default": None},
                        {"name": "ip_address", "type": ["null", "string"], "default": None},
                        {"name": "data", "type": {"type": "map", "values": "string"}},
                        {"name": "tags", "type": {"type": "array", "items": "string"}, "default": []},
                        {"name": "version", "type": "string", "default": "1.0"}
                    ]
                }
            }
        ]
    }
    return json.dumps(schema, indent=2)


class DataQualityCheck:
    """Data quality checks for ingested events"""
    
    @staticmethod
    def check_completeness(data: Dict[str, Any]) -> float:
        """
        Calculate data completeness score (0.0 to 1.0)
        
        Args:
            data: Event payload data
        
        Returns:
            Completeness score
        """
        required_fields = ['event_type', 'source']
        optional_fields = ['user_id', 'session_id', 'ip_address', 'data', 'tags']
        
        present_required = sum(1 for field in required_fields if data.get(field))
        present_optional = sum(1 for field in optional_fields if data.get(field))
        
        total_fields = len(required_fields) + len(optional_fields)
        present_fields = present_required + present_optional
        
        return present_fields / total_fields
    
    @staticmethod
    def check_freshness(timestamp_str: str, max_age_seconds: int = 3600) -> bool:
        """
        Check if event is fresh (not too old)
        
        Args:
            timestamp_str: ISO timestamp string
            max_age_seconds: Maximum acceptable age
        
        Returns:
            True if fresh, False if stale
        """
        try:
            event_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            age = (datetime.now().astimezone() - event_time).total_seconds()
            return age <= max_age_seconds
        except:
            return False
    
    @staticmethod
    def check_consistency(data: Dict[str, Any]) -> List[str]:
        """
        Check data consistency rules
        
        Args:
            data: Event payload data
        
        Returns:
            List of consistency issues found
        """
        issues = []
        
        # Check version format
        version = data.get('version', '1.0')
        if not version.replace('.', '').isdigit():
            issues.append(f"Invalid version format: {version}")
        
        # Check tag consistency
        tags = data.get('tags', [])
        if len(tags) != len(set(tags)):
            issues.append("Duplicate tags found")
        
        # Check data field types
        data_field = data.get('data', {})
        if not isinstance(data_field, dict):
            issues.append("Data field must be a dictionary")
        
        return issues
