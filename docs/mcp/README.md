# MCP Server (Minimal) - DA Agent Lab

## Overview
- ASGI MCP server exposing DA Agent tools for text-to-SQL and business context.
- Built with `modelcontextprotocol` Python SDK and reuses existing tool implementations.

## Tools
- `get_schema()` → returns tables + columns (from SQLite warehouse).
- `dataset_context()` → per-table row_count, min/max dates, top categorical values, sample rows.
- `retrieve_metric_definition(query, top_k=4)` → business metric definitions via RAG index.
- `query_sql(sql, row_limit=None)` → validates read-only SQL, enforces LIMIT, executes safely.

## Run locally
```bash
uv run python -m mcp_server.server
# or
uvicorn mcp_server.server:create_app --factory --host 0.0.0.0 --port 8000
```

## Contract notes
- Validation: `query_sql` calls `validate_sql` with CTE-aware allow-list and forbidden keyword guard.
- Row limits: auto-appends LIMIT (default 200) when absent; override via `row_limit`.
- Dataset context is bounded (3 sample rows, top-3 categorical values) to keep payload small.

## Example MCP client call (pseudo)
```python
import mcp
client = await mcp.connect("http://localhost:8000")
schema = await client.call_tool("get_schema", {})
ctx = await client.call_tool("dataset_context", {})
sql = await client.call_tool("query_sql", {"sql": "SELECT date, dau FROM daily_metrics ORDER BY date DESC"})
```

