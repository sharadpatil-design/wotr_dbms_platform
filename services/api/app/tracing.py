"""
Distributed tracing configuration with OpenTelemetry
"""
import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.kafka import KafkaInstrumentor
from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor


def init_tracing(app, service_name: str = "wotr-api"):
    """
    Initialize OpenTelemetry tracing with Jaeger exporter
    
    Args:
        app: FastAPI application instance
        service_name: Service identifier for traces
    """
    # Check if tracing is enabled
    tracing_enabled = os.getenv("TRACING_ENABLED", "true").lower() == "true"
    if not tracing_enabled:
        print("[Tracing] Tracing disabled via TRACING_ENABLED=false")
        return None
    
    # Jaeger configuration
    jaeger_host = os.getenv("JAEGER_HOST", "jaeger")
    jaeger_port = int(os.getenv("JAEGER_PORT", 6831))
    
    # Create resource with service name
    resource = Resource(attributes={
        "service.name": service_name,
        "service.version": os.getenv("SERVICE_VERSION", "1.0.0"),
        "deployment.environment": os.getenv("ENVIRONMENT", "development"),
    })
    
    # Configure tracer provider
    provider = TracerProvider(resource=resource)
    
    # Configure Jaeger exporter
    jaeger_exporter = JaegerExporter(
        agent_host_name=jaeger_host,
        agent_port=jaeger_port,
    )
    
    # Add span processor
    provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))
    
    # Set global tracer provider
    trace.set_tracer_provider(provider)
    
    # Instrument FastAPI
    FastAPIInstrumentor.instrument_app(app)
    
    # Instrument Kafka
    KafkaInstrumentor().instrument()
    
    # Instrument PostgreSQL
    Psycopg2Instrumentor().instrument()
    
    print(f"[Tracing] Initialized OpenTelemetry tracing: {service_name} -> {jaeger_host}:{jaeger_port}")
    
    return trace.get_tracer(__name__)


def get_tracer():
    """Get the global tracer instance"""
    return trace.get_tracer(__name__)


def add_span_attributes(span, **attributes):
    """
    Add custom attributes to current span
    
    Args:
        span: Current span instance
        **attributes: Key-value pairs to add as attributes
    """
    if span and span.is_recording():
        for key, value in attributes.items():
            span.set_attribute(key, value)


def record_exception(span, exception: Exception):
    """
    Record an exception in the current span
    
    Args:
        span: Current span instance
        exception: Exception to record
    """
    if span and span.is_recording():
        span.record_exception(exception)
        span.set_status(trace.Status(trace.StatusCode.ERROR, str(exception)))
