# DA Agent Lab

**LangGraph-based Data Analyst Agent** — trả lời business/data questions qua SQL tools, RAG retrieval, và full observability.

## Architecture

```
User
 │
 ▼
Streamlit UI :8501   ──HTTP/SSE──►  FastAPI Backend :8001
                                          │
                                          ▼
                                    LangGraph Agent
                                    (SQL / RAG / Mixed)
                                          │
                                    ┌─────┴──────┐
                                    │            │
                                SQLite DB    ConvMemory
                                (warehouse)  (SQLite)

FastMCP Server :8000  (tool surface, independent)
```

---

## Quick Start

### Option A — Local Mode (nhiều terminal)

**Yêu cầu:** Python 3.12+, `uv`

```bash
# 1. Cài dependencies
uv sync

# 2. Seed database (lần đầu)
uv run python data/seeds/create_seed_db.py

# 3. Terminal 1 — Backend (FastAPI)
uv run uvicorn backend.main:app --port 8001 --reload

# 4. Terminal 2 — Frontend (Streamlit)
BACKEND_URL=http://localhost:8001 uv run streamlit run streamlit_app.py

# 5. (Optional) Terminal 3 — MCP Server
uv run python -m mcp_server.server

# 6. (Optional) Terminal 4 — CLI trực tiếp
uv run python -m app.main "DAU 7 ngày gần đây?"
```

**Truy cập:**
| Service | URL |
|---------|-----|
| Streamlit UI | http://localhost:8501 |
| FastAPI docs | http://localhost:8001/docs |
| FastAPI health | http://localhost:8001/health |
| MCP server | http://localhost:8000/mcp |

---

### Option B — Docker Compose Mode

**Yêu cầu:** Docker Engine + Docker Compose v2

**Bước 1 — Cấu hình env:**
```bash
cp .env.docker .env.docker.local
# Mở .env.docker.local và điền các giá trị:
#   LLM_API_URL=...
#   LLM_API_KEY=...
#   E2B_API_KEY=...  (nếu dùng visualization)
```

**Bước 2 — Build và chạy:**
```bash
docker compose --env-file .env.docker.local up --build
```

> Lần đầu build tốn ~5-10 phút do download ML deps (torch, sentence-transformers).
> Các lần sau dùng cache, chỉ ~30 giây.

**Bước 3 — Truy cập (giống Local Mode):**
| Service | URL |
|---------|-----|
| Streamlit UI | http://localhost:8501 |
| FastAPI docs | http://localhost:8001/docs |
| FastAPI health | http://localhost:8001/health |
| MCP server | http://localhost:8000/mcp |

**Các lệnh Docker thường dùng:**
```bash
# Dừng tất cả
docker compose --env-file .env.docker.local down

# Xem logs
docker compose logs -f backend      # Backend logs
docker compose logs -f frontend     # Streamlit logs
docker compose logs -f              # Tất cả

# Restart một service
docker compose --env-file .env.docker.local restart backend

# Rebuild sau khi sửa code
docker compose --env-file .env.docker.local up --build backend

# Reset hoàn toàn (xóa data volumes)
docker compose down -v   # ⚠️ xóa toàn bộ SQLite data
docker compose --env-file .env.docker.local up --build
```

---

## Development Commands

```bash
# Tests
uv run pytest                                       # All tests
uv run pytest tests/test_backend_api.py -v          # Backend API tests
uv run pytest tests/test_sql_tools.py -v            # SQL tools
uv run pytest -k "memory" -v                        # Memory tests
uv run pytest --cov=app --cov-report=term-missing   # Coverage

# Evaluation
uv run python evals/runner.py                       # Full eval suite

# Database
uv run python data/seeds/create_seed_db.py          # Re-seed database

# API smoke tests (backend phải đang chạy)
curl http://localhost:8001/health
curl -X POST http://localhost:8001/query \
  -H "Content-Type: application/json" \
  -d '{"query": "DAU 7 ngày gần đây?", "thread_id": "test-001"}'

# SSE streaming test
curl -N "http://localhost:8001/query/stream?q=DAU+hom+nay&thread_id=test"

# Thread history
curl http://localhost:8001/threads/test-001/history
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_API_URL` | ✅ | — | LLM API endpoint |
| `LLM_API_KEY` | ✅ | — | API key |
| `E2B_API_KEY` | ❌ | — | E2B sandbox (visualization) |
| `BACKEND_URL` | ❌ | `http://localhost:8001` | Backend URL (Streamlit) |
| `SQLITE_DB_PATH` | ❌ | `data/warehouse/analytics.db` | Database path |
| `TRACE_JSONL_PATH` | ❌ | `evals/reports/traces.jsonl` | Trace output |
| `ENABLE_LANGFUSE` | ❌ | `false` | Langfuse tracing |
| `ENABLE_MCP_TOOL_CLIENT` | ❌ | `false` | Use MCP tools |
| `BACKEND_PORT` | ❌ | `8001` | Backend port (Docker) |
| `FRONTEND_PORT` | ❌ | `8501` | Frontend port (Docker) |
| `MCP_PORT` | ❌ | `8000` | MCP port (Docker) |

---

## Project Structure

```
da-agent-project/
├── app/                    # Agent core (LangGraph, tools, memory)
│   ├── graph/              # LangGraph nodes, state, graph builders
│   ├── memory/             # ConversationMemoryStore (SQLite)
│   ├── observability/      # RunTracer (JSONL + Langfuse)
│   └── main.py             # run_query() entry point (UI-agnostic)
├── backend/                # FastAPI backend (HTTP layer)
│   ├── main.py             # App factory
│   ├── routers/            # health, query, threads, evals
│   ├── models/             # Pydantic request/response models
│   ├── services/           # agent_service, sse_service
│   └── http_client.py      # HTTP client dùng bởi Streamlit
├── mcp_server/             # FastMCP server (tool surface)
├── evals/                  # Evaluation suite
├── data/seeds/             # Database seed scripts
├── docker/                 # Dockerfiles
│   ├── backend.Dockerfile
│   └── frontend.Dockerfile
├── streamlit_app.py        # Thin Streamlit UI (HTTP calls only)
├── docker-compose.yml      # Multi-service compose
├── .env.docker             # Docker env template (copy & fill)
└── pyproject.toml          # Dependencies (uv)
```

---

## API Reference

### `GET /health`
```json
{"status": "ok", "version": "1.0.0", "graph_version": "v3"}
```

### `POST /query`
```json
{
  "query": "DAU 7 ngày gần đây?",
  "thread_id": "optional-uuid",
  "user_semantic_context": "optional",
  "version": "v3"
}
```

### `GET /query/stream?q=...&thread_id=...`
SSE streaming. Events:
- `event: started` — ngay lập tức
- `event: result` — full payload sau ~7-10s
- `event: error` — khi lỗi

### `POST /query/upload`
Multipart form: `query`, `thread_id`, `files[]` (CSV)

### `GET /threads/{id}/history?limit=20`
Lịch sử hội thoại theo thứ tự thời gian.

### `DELETE /threads/{id}`
Xóa conversation memory. Idempotent (204).

### `POST /evals/run`
Trigger eval suite chạy nền. Trả về ngay.

---

## Troubleshooting

**Backend offline (Streamlit hiện dấu đỏ):**
```bash
curl http://localhost:8001/health
uv run uvicorn backend.main:app --port 8001 --reload
```

**Docker: port đã bị dùng:**
```bash
lsof -i :8001
# Override trong .env.docker.local:
BACKEND_PORT=8002
```

**Docker: analytics.db chưa có (lần đầu):**
- Backend tự động seed khi startup. Xem log: `docker compose logs backend`

**Xóa data và bắt đầu lại:**
```bash
docker compose down -v && docker compose --env-file .env.docker.local up --build
```
