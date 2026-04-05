# DA Agent Lab

**LangGraph-based Data Analyst Agent** — trả lời business/data questions qua SQL tools, RAG retrieval, Visualization, và Report generation, với full observability.

![DA Agent Lab — Architecture](docs/_media/architecture_flow.png)

---

## What it does

Nhận câu hỏi tiếng Việt hoặc tiếng Anh về business data, tự động:

1. **Phân loại & ground** câu hỏi qua Task Grounder (LLM mini)
2. **Gọi worker phù hợp**: SQL query, RAG retrieval, Visualization, Report
3. **Evaluate artifacts** — nếu chưa đủ → gọi thêm worker; nếu ambiguous → hỏi user
4. **Synthesize câu trả lời** có sức cân, kèm trace đầy đủ

---

## Quick Start

```bash
# 1. Cài dependencies
uv sync

# 2. Seed database (lần đầu)
PYTHONPATH=. python data/seeds/create_seed_db.py

# 3. Backend
uv run uvicorn backend.main:app --port 8001 --reload

# 4. Frontend (terminal khác)
BACKEND_URL=http://localhost:8001 uv run streamlit run streamlit_app.py

# 5. CLI trực tiếp
uv run python -m app.main "Top 5 sản phẩm bán chạy nhất?"
```

| Service | URL |
|---------|-----|
| Streamlit UI | http://localhost:8501 |
| FastAPI docs | http://localhost:8001/docs |
| MCP server | http://localhost:8000/mcp |

---

## Available Tools

Agent exposed **5 high-level tools** qua Leader Agent tool-calling surface:

| Tool | Trigger | What it does |
|------|---------|-------------|
| `ask_sql_analyst` | Data questions, counting, ranking, trend, comparison | Schema lookup → SQL generation → validate → execute → analyze |
| `ask_sql_analyst_parallel` | Multi-part questions (2+ independent sub-queries) | Fan-out parallel SQL workers, merge results |
| `retrieve_rag_answer` | Business definitions, policy, qualitative context | Vector similarity search in uploaded docs |
| `create_visualization` | Inline data values in query (e.g. "vẽ biểu đồ 10, 20, 30") | E2B sandbox → Python/Altair chart |
| `generate_report` | Explicit multi-section report request | 4-phase pipeline: plan → execute → write → critique |

**Low-level internals (not exposed to user):**

| Tool | File | Purpose |
|------|------|---------|
| `validate_sql_query` | `app/tools/validate_sql.py` | AST-based SELECT-only validation + regex block |
| `get_schema_overview` | `app/tools/get_schema.py` | Database schema introspection |
| `ConversationMemoryStore` | `app/memory/store.py` | SQLite session persistence |

---

## Development Commands

```bash
# Tests
uv run pytest                                        # All tests
uv run pytest tests/test_sql_tools.py -v             # SQL tools
uv run pytest -k "memory" -v                        # Memory tests
uv run pytest --cov=app --cov-report=term-missing  # Coverage

# Evaluation
uv run python evals/runner.py                        # Full eval suite

# Database
PYTHONPATH=. python data/seeds/create_seed_db.py      # Re-seed
docker exec da-agent-postgres psql -U postgres -c "\dt"  # List tables

# API smoke tests
curl http://localhost:8001/health
curl -X POST http://localhost:8001/query \
  -H "Content-Type: application/json" \
  -d '{"query": "DAU 7 ngày gần đây?", "thread_id": "test-001"}'
curl -N "http://localhost:8001/query/stream?q=DAU&thread_id=test"
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | ✅ | `postgresql://postgres:postgres@localhost:5432/postgres` | PostgreSQL |
| `LLM_API_URL` | ✅ | — | LLM API endpoint |
| `LLM_API_KEY` | ✅ | — | API key |
| `E2B_API_KEY` | ❌ | — | E2B sandbox (visualization) |
| `BACKEND_URL` | ❌ | `http://localhost:8001` | Streamlit → Backend |
| `TRACE_JSONL_PATH` | ❌ | `evals/reports/traces.jsonl` | JSONL trace output |
| `ENABLE_LANGFUSE` | ❌ | `false` | Langfuse tracing |

---

## Project Structure

```
da-agent-project/
├── app/
│   ├── graph/               # LangGraph nodes, state, graph builders
│   │   ├── graph.py         # build_sql_v3_graph() — 10-node graph
│   │   ├── nodes.py         # leader_agent, artifact_evaluator, clarify_question_node
│   │   ├── task_grounder.py # TaskProfile classifier (LLM mini)
│   │   ├── state.py         # AgentState TypedDict, TaskProfile, WorkerArtifact
│   │   └── standalone_visualization.py  # E2B sandbox viz worker
│   ├── memory/              # ConversationMemoryStore (SQLite)
│   ├── observability/       # RunTracer (JSONL + Langfuse)
│   ├── prompts/             # All LLM prompt definitions
│   ├── tools/               # SQL safety, RAG, schema tools
│   └── main.py             # run_query() — UI-agnostic entry
├── backend/                 # FastAPI HTTP layer
├── mcp_server/             # FastMCP tool surface
├── streamlit_app.py         # Thin Streamlit UI
├── evals/                   # Evaluation suite
├── data/seeds/             # Database seed scripts
├── docker/                 # Dockerfiles
└── docs/                   # Architecture & technical docs
    ├── README.md            # Entry point
    ├── thangquang09/        # Tiếng Việt — architecture, system design, interview
    └── _tech_specs/         # English — state model, worker contracts, observability
```

---

## API Reference

### `POST /query`
```json
{"query": "DAU 7 ngày gần đây?", "thread_id": "optional-uuid", "version": "v3"}
```

### `GET /query/stream?q=...&thread_id=...`
SSE streaming: `started` → `result` / `error`

### `GET /threads/{id}/history`
Conversation history by `thread_id`.

### `DELETE /threads/{id}`
Clear conversation memory (idempotent, 204).

---

## Architecture Highlights

**Hybrid Supervisor Pattern** — Leader Agent (LLM) điều phối, Artifact Evaluator (deterministic code) quyết định stop/continue. Không giao hoàn toàn cho LLM.

**Artifact-based Evaluation** — Mỗi worker trả về `WorkerArtifact` chuẩn hóa: `artifact_type`, `status`, `payload`, `evidence`, `terminal`, `recommended_next_action`.

**Clarify Interrupt** — Khi `task_profile.confidence == "low"` hoặc `task_mode == "ambiguous"`, graph halt tại `clarify_question_node` và hỏi user. Không đoán sai.

**SQL Safety** — Chỉ SELECT. Validation qua sqlglot AST + regex block. CTE extraction để tránh injection.

**Observability-first** — `@trace_node` decorator trên mọi node. JSONL trace + Langfuse prompt versioning + trace replay.
