"""
Schema evolution and versioning support using Avro
"""
import json
import io
from typing import Dict, Any, Optional
from avro import schema, io as avro_io
import logging

logger = logging.getLogger(__name__)


class SchemaRegistry:
    """
    Simple schema registry for managing schema versions
    In production, use Confluent Schema Registry or similar
    """
    
    def __init__(self):
        self.schemas: Dict[str, Dict[int, schema.Schema]] = {}
        self._register_default_schemas()
    
    def _register_default_schemas(self):
        """Register default schema versions"""
        # Version 1.0 - Original schema
        v1_schema = {
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
                            {"name": "event_type", "type": "string"},
                            {"name": "source", "type": "string"},
                            {"name": "data", "type": {"type": "map", "values": "string"}}
                        ]
                    }
                }
            ]
        }
        
        # Version 2.0 - Added optional fields (backward compatible)
        v2_schema = {
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
                            {"name": "event_type", "type": "string"},
                            {"name": "source", "type": "string"},
                            {"name": "user_id", "type": ["null", "string"], "default": None},
                            {"name": "session_id", "type": ["null", "string"], "default": None},
                            {"name": "data", "type": {"type": "map", "values": "string"}},
                            {"name": "tags", "type": {"type": "array", "items": "string"}, "default": []}
                        ]
                    }
                }
            ]
        }
        
        self.register_schema("IngestEvent", 1, v1_schema)
        self.register_schema("IngestEvent", 2, v2_schema)
        logger.info("Registered default schemas: IngestEvent v1, v2")
    
    def register_schema(self, name: str, version: int, schema_dict: Dict[str, Any]):
        """
        Register a schema version
        
        Args:
            name: Schema name
            version: Schema version
            schema_dict: Avro schema as dictionary
        """
        if name not in self.schemas:
            self.schemas[name] = {}
        
        self.schemas[name][version] = schema.parse(json.dumps(schema_dict))
        logger.info(f"Registered schema {name} version {version}")
    
    def get_schema(self, name: str, version: int) -> Optional[schema.Schema]:
        """
        Get schema by name and version
        
        Args:
            name: Schema name
            version: Schema version
        
        Returns:
            Avro schema or None if not found
        """
        return self.schemas.get(name, {}).get(version)
    
    def get_latest_schema(self, name: str) -> Optional[schema.Schema]:
        """
        Get latest version of schema
        
        Args:
            name: Schema name
        
        Returns:
            Latest schema version or None
        """
        if name in self.schemas:
            latest_version = max(self.schemas[name].keys())
            return self.schemas[name][latest_version]
        return None
    
    def list_versions(self, name: str) -> list:
        """List all versions of a schema"""
        return sorted(self.schemas.get(name, {}).keys())


class SchemaEvolution:
    """Handle schema evolution and compatibility checks"""
    
    @staticmethod
    def is_backward_compatible(old_schema: schema.Schema, new_schema: schema.Schema) -> bool:
        """
        Check if new schema is backward compatible with old schema
        (New schema can read data written with old schema)
        
        Args:
            old_schema: Previous schema version
            new_schema: New schema version
        
        Returns:
            True if backward compatible
        """
        try:
            # New schema should have defaults for new fields
            # or make them optional (union with null)
            old_fields = {f.name for f in old_schema.fields}
            new_fields = {f.name for f in new_schema.fields}
            
            # Check removed fields
            removed_fields = old_fields - new_fields
            if removed_fields:
                logger.warning(f"Removed fields (breaks backward compatibility): {removed_fields}")
                return False
            
            # Check added fields have defaults
            added_fields = new_fields - old_fields
            for field_name in added_fields:
                field = next(f for f in new_schema.fields if f.name == field_name)
                if not hasattr(field, 'default') and not SchemaEvolution._is_optional(field.type):
                    logger.warning(f"Added field '{field_name}' without default (breaks backward compatibility)")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Compatibility check failed: {e}")
            return False
    
    @staticmethod
    def is_forward_compatible(old_schema: schema.Schema, new_schema: schema.Schema) -> bool:
        """
        Check if old schema is forward compatible with new schema
        (Old schema can read data written with new schema)
        
        Args:
            old_schema: Previous schema version
            new_schema: New schema version
        
        Returns:
            True if forward compatible
        """
        try:
            old_fields = {f.name for f in old_schema.fields}
            new_fields = {f.name for f in new_schema.fields}
            
            # Check added fields (old schema will ignore them)
            added_fields = new_fields - old_fields
            if added_fields:
                logger.info(f"Added fields (forward compatible): {added_fields}")
            
            # Check removed fields (breaks forward compatibility)
            removed_fields = old_fields - new_fields
            if removed_fields:
                logger.warning(f"Removed fields (breaks forward compatibility): {removed_fields}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Compatibility check failed: {e}")
            return False
    
    @staticmethod
    def _is_optional(field_type) -> bool:
        """Check if field type is optional (union with null)"""
        if isinstance(field_type, schema.UnionSchema):
            return any(isinstance(t, schema.NullSchema) for t in field_type.schemas)
        return False


class AvroSerializer:
    """Serialize/deserialize data using Avro schemas"""
    
    def __init__(self, schema_registry: SchemaRegistry):
        self.registry = schema_registry
    
    def serialize(self, data: Dict[str, Any], schema_name: str, version: int) -> bytes:
        """
        Serialize data to Avro binary format
        
        Args:
            data: Data to serialize
            schema_name: Schema name
            version: Schema version
        
        Returns:
            Serialized data as bytes
        """
        avro_schema = self.registry.get_schema(schema_name, version)
        if not avro_schema:
            raise ValueError(f"Schema {schema_name} version {version} not found")
        
        writer = avro_io.DatumWriter(avro_schema)
        bytes_writer = io.BytesIO()
        encoder = avro_io.BinaryEncoder(bytes_writer)
        
        writer.write(data, encoder)
        return bytes_writer.getvalue()
    
    def deserialize(
        self,
        data: bytes,
        writer_schema_name: str,
        writer_version: int,
        reader_schema_name: Optional[str] = None,
        reader_version: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Deserialize Avro binary data
        
        Args:
            data: Serialized data
            writer_schema_name: Schema used to write data
            writer_version: Version used to write data
            reader_schema_name: Schema to read data with (for evolution)
            reader_version: Version to read data with
        
        Returns:
            Deserialized data
        """
        writer_schema = self.registry.get_schema(writer_schema_name, writer_version)
        if not writer_schema:
            raise ValueError(f"Writer schema {writer_schema_name} v{writer_version} not found")
        
        # Use reader schema if provided (for schema evolution)
        reader_schema = None
        if reader_schema_name and reader_version:
            reader_schema = self.registry.get_schema(reader_schema_name, reader_version)
        
        bytes_reader = io.BytesIO(data)
        decoder = avro_io.BinaryDecoder(bytes_reader)
        
        if reader_schema:
            reader = avro_io.DatumReader(writer_schema, reader_schema)
        else:
            reader = avro_io.DatumReader(writer_schema)
        
        return reader.read(decoder)


# Global schema registry instance
_schema_registry = SchemaRegistry()


def get_schema_registry() -> SchemaRegistry:
    """Get global schema registry instance"""
    return _schema_registry
