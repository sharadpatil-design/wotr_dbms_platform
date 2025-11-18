"""
Structured logging configuration with JSON output
"""
import os
import sys
import logging
from pythonjsonlogger import jsonlogger


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter with additional fields"""
    
    def add_fields(self, log_record, record, message_dict):
        super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
        
        # Add timestamp
        if not log_record.get('timestamp'):
            log_record['timestamp'] = record.created
        
        # Add log level
        if log_record.get('level'):
            log_record['level'] = log_record['level'].upper()
        else:
            log_record['level'] = record.levelname
        
        # Add service name
        log_record['service'] = os.getenv('SERVICE_NAME', 'wotr-api')
        
        # Add environment
        log_record['environment'] = os.getenv('ENVIRONMENT', 'development')
        
        # Add trace context if available
        try:
            from opentelemetry import trace
            span = trace.get_current_span()
            if span and span.get_span_context().is_valid:
                ctx = span.get_span_context()
                log_record['trace_id'] = format(ctx.trace_id, '032x')
                log_record['span_id'] = format(ctx.span_id, '016x')
        except Exception:
            pass


def setup_logging(log_level: str = None):
    """
    Setup structured logging with JSON output
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Get log level from environment or parameter
    if log_level is None:
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    
    # Get log format from environment
    log_format = os.getenv("LOG_FORMAT", "json").lower()
    
    # Create formatter
    if log_format == "json":
        formatter = CustomJsonFormatter(
            '%(timestamp)s %(level)s %(name)s %(message)s'
        )
    else:
        # Plain text format for development
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Add console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # Set log levels for noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("kafka").setLevel(logging.WARNING)
    
    print(f"[Logging] Configured structured logging: level={log_level}, format={log_format}")
    
    return root_logger


def get_logger(name: str):
    """
    Get a logger instance with structured logging configured
    
    Args:
        name: Logger name (usually __name__)
    
    Returns:
        Logger instance
    """
    return logging.getLogger(name)


# Context manager for request logging
class RequestLogger:
    """Context manager for logging request lifecycle"""
    
    def __init__(self, logger, request_id: str, method: str, path: str):
        self.logger = logger
        self.request_id = request_id
        self.method = method
        self.path = path
        self.start_time = None
    
    def __enter__(self):
        import time
        self.start_time = time.time()
        self.logger.info(
            "Request started",
            extra={
                "request_id": self.request_id,
                "method": self.method,
                "path": self.path,
            }
        )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        import time
        duration = time.time() - self.start_time
        
        if exc_type:
            self.logger.error(
                "Request failed",
                extra={
                    "request_id": self.request_id,
                    "method": self.method,
                    "path": self.path,
                    "duration": duration,
                    "error": str(exc_val),
                    "error_type": exc_type.__name__,
                },
                exc_info=True
            )
        else:
            self.logger.info(
                "Request completed",
                extra={
                    "request_id": self.request_id,
                    "method": self.method,
                    "path": self.path,
                    "duration": duration,
                }
            )
        
        return False  # Don't suppress exceptions
