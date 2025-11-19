"""
Dead Letter Queue (DLQ) implementation for failed messages
"""
import os
import json
import time
from typing import Dict, Any, Optional
from datetime import datetime
from kafka import KafkaProducer
from minio import Minio
import logging

logger = logging.getLogger(__name__)


class DeadLetterQueue:
    """
    Dead Letter Queue for handling failed message processing
    Stores failed messages to MinIO and Kafka DLQ topic
    """
    
    def __init__(
        self,
        minio_client: Minio,
        kafka_producer: KafkaProducer,
        dlq_bucket: str = "dead-letters",
        dlq_topic: str = "dlq-events",
        max_retries: int = 3
    ):
        """
        Initialize DLQ
        
        Args:
            minio_client: MinIO client instance
            kafka_producer: Kafka producer instance
            dlq_bucket: MinIO bucket for DLQ storage
            dlq_topic: Kafka topic for DLQ messages
            max_retries: Maximum retry attempts before DLQ
        """
        self.minio = minio_client
        self.kafka = kafka_producer
        self.dlq_bucket = dlq_bucket
        self.dlq_topic = dlq_topic
        self.max_retries = max_retries
        
        # Ensure DLQ bucket exists
        if not self.minio.bucket_exists(dlq_bucket):
            self.minio.make_bucket(dlq_bucket)
            logger.info(f"Created DLQ bucket: {dlq_bucket}")
    
    def send_to_dlq(
        self,
        original_message: Dict[str, Any],
        error: Exception,
        retry_count: int = 0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Send failed message to DLQ
        
        Args:
            original_message: The message that failed processing
            error: Exception that caused the failure
            retry_count: Number of retry attempts
            metadata: Additional metadata about the failure
        
        Returns:
            DLQ message ID
        """
        dlq_id = f"dlq_{int(time.time() * 1000)}_{original_message.get('id', 'unknown')}"
        
        # Build DLQ envelope
        dlq_message = {
            "dlq_id": dlq_id,
            "original_message": original_message,
            "error": {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": str(error.__traceback__) if hasattr(error, '__traceback__') else None
            },
            "retry_count": retry_count,
            "failed_at": datetime.utcnow().isoformat(),
            "metadata": metadata or {}
        }
        
        try:
            # Store to MinIO
            self._store_to_minio(dlq_id, dlq_message)
            
            # Publish to DLQ Kafka topic
            self._publish_to_kafka(dlq_message)
            
            logger.warning(
                f"Message sent to DLQ: {dlq_id}",
                extra={
                    "dlq_id": dlq_id,
                    "error_type": type(error).__name__,
                    "retry_count": retry_count,
                    "original_id": original_message.get('id')
                }
            )
            
            return dlq_id
            
        except Exception as e:
            logger.error(f"Failed to send message to DLQ: {e}", exc_info=True)
            # Fall back to file system storage if DLQ fails
            self._fallback_to_file(dlq_id, dlq_message)
            raise
    
    def _store_to_minio(self, dlq_id: str, message: Dict[str, Any]):
        """Store DLQ message to MinIO"""
        import io
        
        key = f"failed/{datetime.utcnow().strftime('%Y/%m/%d')}/{dlq_id}.json"
        data = json.dumps(message, indent=2).encode('utf-8')
        
        self.minio.put_object(
            self.dlq_bucket,
            key,
            io.BytesIO(data),
            len(data),
            content_type="application/json"
        )
        
        logger.debug(f"Stored DLQ message to MinIO: {key}")
    
    def _publish_to_kafka(self, message: Dict[str, Any]):
        """Publish DLQ message to Kafka"""
        self.kafka.send(
            self.dlq_topic,
            json.dumps(message).encode('utf-8')
        )
        self.kafka.flush()
        
        logger.debug(f"Published DLQ message to Kafka topic: {self.dlq_topic}")
    
    def _fallback_to_file(self, dlq_id: str, message: Dict[str, Any]):
        """Fallback: write DLQ message to local file"""
        fallback_dir = "/tmp/dlq_fallback"
        os.makedirs(fallback_dir, exist_ok=True)
        
        filepath = os.path.join(fallback_dir, f"{dlq_id}.json")
        with open(filepath, 'w') as f:
            json.dump(message, f, indent=2)
        
        logger.warning(f"DLQ message written to fallback file: {filepath}")
    
    def should_retry(self, retry_count: int) -> bool:
        """
        Determine if message should be retried
        
        Args:
            retry_count: Current retry count
        
        Returns:
            True if should retry, False if should go to DLQ
        """
        return retry_count < self.max_retries
    
    def calculate_backoff(self, retry_count: int, base_delay: float = 1.0) -> float:
        """
        Calculate exponential backoff delay
        
        Args:
            retry_count: Current retry attempt
            base_delay: Base delay in seconds
        
        Returns:
            Delay in seconds
        """
        return base_delay * (2 ** retry_count)


class RetryableMessage:
    """Wrapper for messages with retry logic"""
    
    def __init__(self, message: Dict[str, Any], max_retries: int = 3):
        self.message = message
        self.max_retries = max_retries
        self.retry_count = 0
        self.last_error: Optional[Exception] = None
    
    def can_retry(self) -> bool:
        """Check if message can be retried"""
        return self.retry_count < self.max_retries
    
    def increment_retry(self):
        """Increment retry counter"""
        self.retry_count += 1
    
    def get_backoff_delay(self) -> float:
        """Get exponential backoff delay"""
        return 2 ** self.retry_count  # 1s, 2s, 4s, 8s, etc.
    
    def record_error(self, error: Exception):
        """Record the error that caused failure"""
        self.last_error = error


def create_dlq_metrics():
    """Create Prometheus metrics for DLQ monitoring"""
    from prometheus_client import Counter, Gauge
    
    DLQ_MESSAGES = Counter(
        "dlq_messages_total",
        "Total messages sent to DLQ",
        ["error_type"]
    )
    
    DLQ_RETRIES = Counter(
        "dlq_retry_attempts_total",
        "Total retry attempts before DLQ"
    )
    
    DLQ_BACKLOG = Gauge(
        "dlq_backlog_size",
        "Current number of messages in DLQ"
    )
    
    return {
        "messages": DLQ_MESSAGES,
        "retries": DLQ_RETRIES,
        "backlog": DLQ_BACKLOG
    }
