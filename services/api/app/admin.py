"""
Admin Dashboard for WOTR Platform Management
"""
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import psycopg2
from clickhouse_driver import Client as ClickHouseClient
from minio import Minio
from kafka import KafkaAdminClient
import os
from .auth import get_api_key

router = APIRouter(prefix="/admin", tags=["admin"])


# --- Data Models ---
class SystemStats(BaseModel):
    """Overall system statistics"""
    total_events: int
    events_last_hour: int
    events_last_24h: int
    validation_failures: int
    dlq_messages: int
    active_sessions: int
    storage_used_mb: float


class ServiceHealth(BaseModel):
    """Service health status"""
    service: str
    status: str
    latency_ms: Optional[float]
    last_check: str


class EventStats(BaseModel):
    """Event statistics by type"""
    event_type: str
    count: int
    avg_size_bytes: float
    last_event: str


class DLQMessage(BaseModel):
    """Dead letter queue message"""
    dlq_id: str
    original_id: str
    error_type: str
    error_message: str
    retry_count: int
    failed_at: str


# --- Helper Functions ---
def get_postgres_conn():
    """Get PostgreSQL connection"""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", 5432)),
        dbname=os.getenv("POSTGRES_DB", "wotr"),
        user=os.getenv("POSTGRES_USER", "admin"),
        password=os.getenv("POSTGRES_PASSWORD", "admin")
    )


def get_clickhouse_client():
    """Get ClickHouse client"""
    return ClickHouseClient(
        host=os.getenv("CLICKHOUSE_HOST", "clickhouse"),
        port=int(os.getenv("CLICKHOUSE_PORT", 9000)),
        user=os.getenv("CLICKHOUSE_USER", "wotr"),
        password=os.getenv("CLICKHOUSE_PASSWORD", "wotrpass")
    )


def get_minio_client():
    """Get MinIO client"""
    endpoint = os.getenv("MINIO_ENDPOINT", "minio:9000").replace("http://", "").replace("https://", "")
    return Minio(
        endpoint,
        access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
        secure=False
    )


# --- Dashboard Endpoints ---
@router.get("/", response_class=HTMLResponse)
async def dashboard_home():
    """Admin dashboard home page"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>WOTR Admin Dashboard</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; background: #f5f5f5; }
            .header { background: #1a73e8; color: white; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .header h1 { font-size: 24px; }
            .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
            .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 30px; }
            .stat-card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
            .stat-card h3 { font-size: 14px; color: #666; margin-bottom: 10px; text-transform: uppercase; }
            .stat-card .value { font-size: 32px; font-weight: bold; color: #1a73e8; }
            .stat-card .change { font-size: 12px; color: #0f9d58; margin-top: 5px; }
            .section { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 20px; }
            .section h2 { font-size: 18px; margin-bottom: 15px; color: #333; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #e0e0e0; }
            th { background: #f5f5f5; font-weight: 600; color: #666; font-size: 12px; text-transform: uppercase; }
            .status-ok { color: #0f9d58; font-weight: 600; }
            .status-error { color: #d93025; font-weight: 600; }
            .btn { padding: 8px 16px; background: #1a73e8; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
            .btn:hover { background: #1557b0; }
            .btn-danger { background: #d93025; }
            .btn-danger:hover { background: #b71c1c; }
            .nav { display: flex; gap: 20px; margin-bottom: 20px; }
            .nav a { color: #1a73e8; text-decoration: none; padding: 10px; font-weight: 500; }
            .nav a:hover { background: #e8f0fe; border-radius: 4px; }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🚀 WOTR Admin Dashboard</h1>
        </div>
        <div class="container">
            <div class="nav">
                <a href="/admin/">Dashboard</a>
                <a href="/admin/stats">Statistics</a>
                <a href="/admin/services">Services</a>
                <a href="/admin/dlq">Dead Letter Queue</a>
                <a href="/admin/query">Data Explorer</a>
                <a href="/docs">API Docs</a>
            </div>
            
            <div class="stats-grid" id="stats-grid">
                <div class="stat-card">
                    <h3>Total Events</h3>
                    <div class="value" id="total-events">-</div>
                    <div class="change">↑ Last 24h</div>
                </div>
                <div class="stat-card">
                    <h3>Events/Hour</h3>
                    <div class="value" id="events-hour">-</div>
                    <div class="change">Current rate</div>
                </div>
                <div class="stat-card">
                    <h3>DLQ Messages</h3>
                    <div class="value" id="dlq-count">-</div>
                    <div class="change">Failed processing</div>
                </div>
                <div class="stat-card">
                    <h3>Storage Used</h3>
                    <div class="value" id="storage-used">-</div>
                    <div class="change">MinIO + ClickHouse</div>
                </div>
            </div>

            <div class="section">
                <h2>Service Health</h2>
                <table id="services-table">
                    <thead>
                        <tr>
                            <th>Service</th>
                            <th>Status</th>
                            <th>Latency</th>
                            <th>Last Check</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr><td colspan="4">Loading...</td></tr>
                    </tbody>
                </table>
            </div>

            <div class="section">
                <h2>Recent Events by Type</h2>
                <table id="events-table">
                    <thead>
                        <tr>
                            <th>Event Type</th>
                            <th>Count</th>
                            <th>Avg Size</th>
                            <th>Last Event</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr><td colspan="4">Loading...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <script>
            async function loadStats() {
                try {
                    const response = await fetch('/admin/stats');
                    const data = await response.json();
                    
                    document.getElementById('total-events').textContent = data.total_events.toLocaleString();
                    document.getElementById('events-hour').textContent = data.events_last_hour.toLocaleString();
                    document.getElementById('dlq-count').textContent = data.dlq_messages.toLocaleString();
                    document.getElementById('storage-used').textContent = data.storage_used_mb.toFixed(2) + ' MB';
                } catch (e) {
                    console.error('Failed to load stats:', e);
                }
            }

            async function loadServices() {
                try {
                    const response = await fetch('/admin/services');
                    const services = await response.json();
                    
                    const tbody = document.querySelector('#services-table tbody');
                    tbody.innerHTML = services.map(s => `
                        <tr>
                            <td>${s.service}</td>
                            <td class="status-${s.status === 'ok' ? 'ok' : 'error'}">${s.status.toUpperCase()}</td>
                            <td>${s.latency_ms ? s.latency_ms.toFixed(2) + 'ms' : '-'}</td>
                            <td>${new Date(s.last_check).toLocaleString()}</td>
                        </tr>
                    `).join('');
                } catch (e) {
                    console.error('Failed to load services:', e);
                }
            }

            async function loadEventStats() {
                try {
                    const response = await fetch('/admin/events/stats');
                    const events = await response.json();
                    
                    const tbody = document.querySelector('#events-table tbody');
                    tbody.innerHTML = events.map(e => `
                        <tr>
                            <td>${e.event_type}</td>
                            <td>${e.count.toLocaleString()}</td>
                            <td>${(e.avg_size_bytes / 1024).toFixed(2)} KB</td>
                            <td>${new Date(e.last_event).toLocaleString()}</td>
                        </tr>
                    `).join('');
                } catch (e) {
                    console.error('Failed to load event stats:', e);
                }
            }

            // Load data on page load
            loadStats();
            loadServices();
            loadEventStats();

            // Refresh every 10 seconds
            setInterval(() => {
                loadStats();
                loadServices();
                loadEventStats();
            }, 10000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@router.get("/stats")
async def get_system_stats(api_key: str = Depends(get_api_key)) -> SystemStats:
    """Get system statistics"""
    try:
        ch = get_clickhouse_client()
        
        # Total events
        total_events = ch.execute("SELECT count() FROM wotr.ingested_data")[0][0]
        
        # Events last hour
        events_last_hour = ch.execute("""
            SELECT count() FROM wotr.ingested_data
            WHERE created_at >= now() - INTERVAL 1 HOUR
        """)[0][0]
        
        # Events last 24 hours
        events_last_24h = ch.execute("""
            SELECT count() FROM wotr.ingested_data
            WHERE created_at >= now() - INTERVAL 1 DAY
        """)[0][0]
        
        # Validation failures
        validation_failures = ch.execute("""
            SELECT count() FROM wotr.ingested_data
            WHERE validation_status = 'failed'
        """)[0][0]
        
        # DLQ messages (approximate from MinIO)
        minio = get_minio_client()
        dlq_count = 0
        try:
            if minio.bucket_exists("dead-letters"):
                objects = list(minio.list_objects("dead-letters", prefix="failed/", recursive=True))
                dlq_count = len(objects)
        except:
            pass
        
        # Storage used (ClickHouse)
        storage_result = ch.execute("""
            SELECT sum(bytes) / 1024 / 1024 as mb
            FROM system.parts
            WHERE database = 'wotr' AND table = 'ingested_data'
        """)
        storage_used_mb = storage_result[0][0] if storage_result[0][0] else 0.0
        
        return SystemStats(
            total_events=total_events,
            events_last_hour=events_last_hour,
            events_last_24h=events_last_24h,
            validation_failures=validation_failures,
            dlq_messages=dlq_count,
            active_sessions=0,  # TODO: Implement session tracking
            storage_used_mb=storage_used_mb
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@router.get("/services")
async def get_service_health(api_key: str = Depends(get_api_key)) -> List[ServiceHealth]:
    """Get health status of all services"""
    import time
    
    services = []
    
    # PostgreSQL
    try:
        start = time.time()
        conn = get_postgres_conn()
        conn.cursor().execute("SELECT 1")
        conn.close()
        latency = (time.time() - start) * 1000
        services.append(ServiceHealth(
            service="PostgreSQL",
            status="ok",
            latency_ms=latency,
            last_check=datetime.utcnow().isoformat()
        ))
    except Exception as e:
        services.append(ServiceHealth(
            service="PostgreSQL",
            status=f"error: {str(e)}",
            latency_ms=None,
            last_check=datetime.utcnow().isoformat()
        ))
    
    # ClickHouse
    try:
        start = time.time()
        ch = get_clickhouse_client()
        ch.execute("SELECT 1")
        latency = (time.time() - start) * 1000
        services.append(ServiceHealth(
            service="ClickHouse",
            status="ok",
            latency_ms=latency,
            last_check=datetime.utcnow().isoformat()
        ))
    except Exception as e:
        services.append(ServiceHealth(
            service="ClickHouse",
            status=f"error: {str(e)}",
            latency_ms=None,
            last_check=datetime.utcnow().isoformat()
        ))
    
    # MinIO
    try:
        start = time.time()
        minio = get_minio_client()
        list(minio.list_buckets())
        latency = (time.time() - start) * 1000
        services.append(ServiceHealth(
            service="MinIO",
            status="ok",
            latency_ms=latency,
            last_check=datetime.utcnow().isoformat()
        ))
    except Exception as e:
        services.append(ServiceHealth(
            service="MinIO",
            status=f"error: {str(e)}",
            latency_ms=None,
            last_check=datetime.utcnow().isoformat()
        ))
    
    return services


@router.get("/events/stats")
async def get_event_stats(api_key: str = Depends(get_api_key)) -> List[EventStats]:
    """Get statistics by event type"""
    try:
        ch = get_clickhouse_client()
        
        results = ch.execute("""
            SELECT
                event_type,
                count() as count,
                avg(length(payload)) as avg_size,
                max(created_at) as last_event
            FROM wotr.ingested_data
            WHERE created_at >= now() - INTERVAL 24 HOUR
            GROUP BY event_type
            ORDER BY count DESC
            LIMIT 20
        """)
        
        return [
            EventStats(
                event_type=row[0],
                count=row[1],
                avg_size_bytes=row[2],
                last_event=row[3].isoformat()
            )
            for row in results
        ]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get event stats: {str(e)}")


@router.get("/dlq/messages")
async def get_dlq_messages(
    limit: int = 50,
    api_key: str = Depends(get_api_key)
) -> List[DLQMessage]:
    """Get DLQ messages from MinIO"""
    import json
    
    try:
        minio = get_minio_client()
        messages = []
        
        if not minio.bucket_exists("dead-letters"):
            return []
        
        objects = list(minio.list_objects("dead-letters", prefix="failed/", recursive=True))[:limit]
        
        for obj in objects:
            try:
                data = minio.get_object("dead-letters", obj.object_name)
                dlq_message = json.loads(data.read().decode('utf-8'))
                
                messages.append(DLQMessage(
                    dlq_id=dlq_message.get("dlq_id", ""),
                    original_id=dlq_message.get("original_message", {}).get("id", ""),
                    error_type=dlq_message.get("error", {}).get("type", ""),
                    error_message=dlq_message.get("error", {}).get("message", ""),
                    retry_count=dlq_message.get("retry_count", 0),
                    failed_at=dlq_message.get("failed_at", "")
                ))
            except:
                continue
        
        return messages
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get DLQ messages: {str(e)}")


@router.post("/dlq/{dlq_id}/retry")
async def retry_dlq_message(dlq_id: str, api_key: str = Depends(get_api_key)):
    """Retry a DLQ message by re-ingesting it"""
    # TODO: Implement DLQ message retry logic
    return {"message": f"Retry initiated for {dlq_id}"}


@router.delete("/dlq/{dlq_id}")
async def delete_dlq_message(dlq_id: str, api_key: str = Depends(get_api_key)):
    """Delete a DLQ message"""
    # TODO: Implement DLQ message deletion
    return {"message": f"Deleted {dlq_id}"}
