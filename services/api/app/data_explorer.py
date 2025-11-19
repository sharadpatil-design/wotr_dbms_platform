"""
ClickHouse Data Explorer - Interactive query interface
"""
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from clickhouse_driver import Client as ClickHouseClient
import os
from auth import get_api_key

router = APIRouter(prefix="/explorer", tags=["data-explorer"])


class QueryRequest(BaseModel):
    """Query request model"""
    query: str
    limit: Optional[int] = 1000
    format: Optional[str] = "json"  # json, csv, table


class QueryResult(BaseModel):
    """Query result model"""
    columns: List[str]
    rows: List[List[Any]]
    row_count: int
    execution_time_ms: float


class SavedQuery(BaseModel):
    """Saved query model"""
    name: str
    description: str
    query: str
    category: str


# Predefined queries for common operations
SAVED_QUERIES = {
    "event_distribution": SavedQuery(
        name="Event Distribution (24h)",
        description="Count of events by type in the last 24 hours",
        query="""
SELECT
    event_type,
    count() as count,
    round(avg(length(payload)), 2) as avg_size_bytes
FROM wotr.ingested_data
WHERE created_at >= now() - INTERVAL 24 HOUR
GROUP BY event_type
ORDER BY count DESC
        """,
        category="analytics"
    ),
    "hourly_trend": SavedQuery(
        name="Hourly Event Trend",
        description="Events per hour for the last 24 hours",
        query="""
SELECT
    toStartOfHour(created_at) as hour,
    count() as event_count
FROM wotr.ingested_data
WHERE created_at >= now() - INTERVAL 24 HOUR
GROUP BY hour
ORDER BY hour DESC
        """,
        category="analytics"
    ),
    "top_sources": SavedQuery(
        name="Top Event Sources",
        description="Top 20 event sources by volume",
        query="""
SELECT
    source,
    count() as count,
    uniq(id) as unique_events
FROM wotr.ingested_data
WHERE created_at >= now() - INTERVAL 24 HOUR
GROUP BY source
ORDER BY count DESC
LIMIT 20
        """,
        category="analytics"
    ),
    "validation_failures": SavedQuery(
        name="Validation Failures",
        description="Events that failed validation",
        query="""
SELECT
    id,
    timestamp,
    event_type,
    source,
    created_at
FROM wotr.ingested_data
WHERE validation_status = 'failed'
ORDER BY created_at DESC
LIMIT 100
        """,
        category="troubleshooting"
    ),
    "recent_events": SavedQuery(
        name="Recent Events",
        description="Last 50 events ingested",
        query="""
SELECT
    id,
    timestamp,
    event_type,
    source,
    length(payload) as size_bytes,
    created_at
FROM wotr.ingested_data
ORDER BY created_at DESC
LIMIT 50
        """,
        category="monitoring"
    ),
    "table_stats": SavedQuery(
        name="Table Statistics",
        description="Storage and row statistics for ingested_data table",
        query="""
SELECT
    database,
    table,
    formatReadableSize(sum(bytes)) as size,
    sum(rows) as row_count,
    count() as part_count,
    max(modification_time) as last_modified
FROM system.parts
WHERE database = 'wotr' AND table = 'ingested_data' AND active = 1
GROUP BY database, table
        """,
        category="system"
    ),
    "partition_info": SavedQuery(
        name="Partition Information",
        description="Data distribution across partitions",
        query="""
SELECT
    partition,
    sum(rows) as rows,
    formatReadableSize(sum(bytes)) as size,
    count() as parts
FROM system.parts
WHERE database = 'wotr' AND table = 'ingested_data' AND active = 1
GROUP BY partition
ORDER BY partition DESC
LIMIT 12
        """,
        category="system"
    )
}


def get_clickhouse_client():
    """Get ClickHouse client"""
    return ClickHouseClient(
        host=os.getenv("CLICKHOUSE_HOST", "clickhouse"),
        port=int(os.getenv("CLICKHOUSE_PORT", 9000)),
        user=os.getenv("CLICKHOUSE_USER", "wotr"),
        password=os.getenv("CLICKHOUSE_PASSWORD", "wotrpass")
    )


@router.get("/", response_class=HTMLResponse)
async def explorer_home():
    """Data explorer UI"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>ClickHouse Data Explorer</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: 'Monaco', 'Menlo', 'Courier New', monospace; background: #1e1e1e; color: #d4d4d4; }
            .header { background: #252526; padding: 15px 20px; border-bottom: 1px solid #3e3e42; }
            .header h1 { font-size: 18px; color: #4fc3f7; }
            .container { display: flex; height: calc(100vh - 52px); }
            .sidebar { width: 250px; background: #252526; border-right: 1px solid #3e3e42; overflow-y: auto; }
            .main { flex: 1; display: flex; flex-direction: column; }
            .query-editor { flex: 0 0 200px; background: #1e1e1e; border-bottom: 1px solid #3e3e42; padding: 10px; }
            .results { flex: 1; background: #1e1e1e; overflow: auto; padding: 10px; }
            .query-item { padding: 12px 15px; cursor: pointer; border-bottom: 1px solid #3e3e42; }
            .query-item:hover { background: #2d2d30; }
            .query-item h3 { font-size: 13px; color: #4fc3f7; margin-bottom: 4px; }
            .query-item p { font-size: 11px; color: #858585; }
            .category { padding: 10px 15px; font-size: 11px; color: #858585; text-transform: uppercase; font-weight: bold; }
            textarea { width: 100%; height: 150px; background: #1e1e1e; color: #d4d4d4; border: 1px solid #3e3e42; padding: 10px; font-family: inherit; font-size: 13px; resize: vertical; }
            .toolbar { display: flex; gap: 10px; margin-top: 10px; align-items: center; }
            .btn { padding: 8px 16px; background: #0e639c; color: white; border: none; border-radius: 3px; cursor: pointer; font-size: 13px; }
            .btn:hover { background: #1177bb; }
            .btn-clear { background: #3e3e42; }
            .btn-clear:hover { background: #505050; }
            table { width: 100%; border-collapse: collapse; font-size: 12px; }
            th, td { padding: 8px 12px; text-align: left; border: 1px solid #3e3e42; }
            th { background: #252526; color: #4fc3f7; font-weight: 600; position: sticky; top: 0; }
            tr:hover { background: #2d2d30; }
            .info { padding: 10px; background: #252526; color: #858585; font-size: 12px; margin-bottom: 10px; border-radius: 3px; }
            .error { background: #5a1d1d; color: #f48771; padding: 10px; margin-bottom: 10px; border-radius: 3px; font-size: 12px; }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🔍 ClickHouse Data Explorer</h1>
        </div>
        <div class="container">
            <div class="sidebar">
                <div class="category">📊 Analytics</div>
                <div class="query-item" onclick="loadQuery('event_distribution')">
                    <h3>Event Distribution (24h)</h3>
                    <p>Count by event type</p>
                </div>
                <div class="query-item" onclick="loadQuery('hourly_trend')">
                    <h3>Hourly Event Trend</h3>
                    <p>Events per hour</p>
                </div>
                <div class="query-item" onclick="loadQuery('top_sources')">
                    <h3>Top Event Sources</h3>
                    <p>Top 20 sources</p>
                </div>
                
                <div class="category">🔧 Troubleshooting</div>
                <div class="query-item" onclick="loadQuery('validation_failures')">
                    <h3>Validation Failures</h3>
                    <p>Failed events</p>
                </div>
                
                <div class="category">📈 Monitoring</div>
                <div class="query-item" onclick="loadQuery('recent_events')">
                    <h3>Recent Events</h3>
                    <p>Last 50 events</p>
                </div>
                
                <div class="category">⚙️ System</div>
                <div class="query-item" onclick="loadQuery('table_stats')">
                    <h3>Table Statistics</h3>
                    <p>Storage & rows</p>
                </div>
                <div class="query-item" onclick="loadQuery('partition_info')">
                    <h3>Partition Information</h3>
                    <p>Data distribution</p>
                </div>
            </div>
            
            <div class="main">
                <div class="query-editor">
                    <textarea id="query-input" placeholder="Enter your SQL query..."></textarea>
                    <div class="toolbar">
                        <button class="btn" onclick="executeQuery()">▶ Execute</button>
                        <button class="btn btn-clear" onclick="clearQuery()">Clear</button>
                        <span style="color: #858585; font-size: 12px; margin-left: auto;" id="query-info"></span>
                    </div>
                </div>
                
                <div class="results" id="results">
                    <div class="info">
                        👈 Select a saved query from the sidebar or write your own SQL query above
                    </div>
                </div>
            </div>
        </div>

        <script>
            const savedQueries = """ + str(SAVED_QUERIES).replace("'", '"') + """;
            
            function loadQuery(queryKey) {
                fetch(`/explorer/saved/${queryKey}`)
                    .then(r => r.json())
                    .then(data => {
                        document.getElementById('query-input').value = data.query.trim();
                        document.getElementById('query-info').textContent = data.description;
                    });
            }
            
            function clearQuery() {
                document.getElementById('query-input').value = '';
                document.getElementById('query-info').textContent = '';
                document.getElementById('results').innerHTML = '<div class="info">Query cleared</div>';
            }
            
            async function executeQuery() {
                const query = document.getElementById('query-input').value.trim();
                if (!query) {
                    document.getElementById('results').innerHTML = '<div class="error">Please enter a query</div>';
                    return;
                }
                
                document.getElementById('results').innerHTML = '<div class="info">⏳ Executing query...</div>';
                
                try {
                    const response = await fetch('/explorer/query', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ query: query })
                    });
                    
                    if (!response.ok) {
                        const error = await response.json();
                        document.getElementById('results').innerHTML = `<div class="error">❌ Error: ${error.detail}</div>`;
                        return;
                    }
                    
                    const data = await response.json();
                    displayResults(data);
                } catch (e) {
                    document.getElementById('results').innerHTML = `<div class="error">❌ Error: ${e.message}</div>`;
                }
            }
            
            function displayResults(data) {
                const info = `✅ ${data.row_count} rows in ${data.execution_time_ms.toFixed(2)}ms`;
                
                let html = `<div class="info">${info}</div>`;
                
                if (data.row_count === 0) {
                    html += '<div class="info">No results found</div>';
                } else {
                    html += '<table><thead><tr>';
                    data.columns.forEach(col => {
                        html += `<th>${col}</th>`;
                    });
                    html += '</tr></thead><tbody>';
                    
                    data.rows.forEach(row => {
                        html += '<tr>';
                        row.forEach(cell => {
                            html += `<td>${cell !== null ? cell : '<i>null</i>'}</td>`;
                        });
                        html += '</tr>';
                    });
                    
                    html += '</tbody></table>';
                }
                
                document.getElementById('results').innerHTML = html;
            }
            
            // Execute query on Ctrl/Cmd + Enter
            document.getElementById('query-input').addEventListener('keydown', (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                    executeQuery();
                }
            });
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@router.get("/saved/{query_name}")
async def get_saved_query(query_name: str):
    """Get a saved query"""
    if query_name not in SAVED_QUERIES:
        raise HTTPException(status_code=404, detail="Query not found")
    
    return SAVED_QUERIES[query_name]


@router.get("/saved")
async def list_saved_queries() -> List[SavedQuery]:
    """List all saved queries"""
    return list(SAVED_QUERIES.values())


@router.post("/query")
async def execute_query(
    request: QueryRequest,
    api_key: str = Depends(get_api_key)
) -> QueryResult:
    """Execute a ClickHouse query"""
    import time
    
    # Basic SQL injection prevention
    forbidden_keywords = ["DROP", "DELETE", "TRUNCATE", "INSERT", "UPDATE", "ALTER", "CREATE"]
    query_upper = request.query.upper()
    
    for keyword in forbidden_keywords:
        if keyword in query_upper:
            raise HTTPException(
                status_code=400,
                detail=f"Forbidden keyword: {keyword}. Only SELECT queries are allowed."
            )
    
    try:
        ch = get_clickhouse_client()
        
        start_time = time.time()
        result = ch.execute(request.query, with_column_types=True)
        execution_time = (time.time() - start_time) * 1000
        
        if not result:
            return QueryResult(
                columns=[],
                rows=[],
                row_count=0,
                execution_time_ms=execution_time
            )
        
        rows_data, columns_info = result
        columns = [col[0] for col in columns_info]
        
        # Apply limit
        rows = rows_data[:request.limit]
        
        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            execution_time_ms=execution_time
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query execution failed: {str(e)}")


@router.get("/schema")
async def get_schema(api_key: str = Depends(get_api_key)):
    """Get database schema information"""
    try:
        ch = get_clickhouse_client()
        
        # Get tables
        tables = ch.execute("""
            SELECT
                database,
                name as table,
                engine,
                total_rows,
                formatReadableSize(total_bytes) as size
            FROM system.tables
            WHERE database = 'wotr'
        """)
        
        # Get columns for each table
        schema = {}
        for table_info in tables:
            table_name = table_info[1]
            columns = ch.execute(f"""
                SELECT
                    name,
                    type,
                    default_kind,
                    default_expression
                FROM system.columns
                WHERE database = 'wotr' AND table = '{table_name}'
                ORDER BY position
            """)
            
            schema[table_name] = {
                "info": {
                    "database": table_info[0],
                    "engine": table_info[2],
                    "rows": table_info[3],
                    "size": table_info[4]
                },
                "columns": [
                    {
                        "name": col[0],
                        "type": col[1],
                        "default_kind": col[2],
                        "default_expression": col[3]
                    }
                    for col in columns
                ]
            }
        
        return schema
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get schema: {str(e)}")
