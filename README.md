# DA Agent Lab

**LangGraph-based Data Analyst Agent** — trả lời business/data questions qua SQL tools, Visualization, và Report generation, với full observability.

![DA Agent Lab — Architecture](docs/_media/architecture_flow.png)

---

## Live Demo

- Frontend demo: https://da-agent-project.vercel.app/

## What it does

DA Agent Lab nhận câu hỏi tiếng Việt/tiếng Anh về business data — từ đơn giản ("DAU hôm qua?") đến phức tạp ("So sánh retention cohort tháng này với tháng trước rồi vẽ chart") — và tự động hoàn thiện:

- **Phân loại & Ground** — Task Grounder (LLM mini) phân loại query thành `TaskProfile` (mode, source, required capabilities, confidence). Nếu query ambiguous → halt và hỏi user. Chitchat bypass pipeline.
- **Plan-Execute Loop** — Leader Agent sử dụng plan-execute pattern (≤5 steps): lập kế hoạch → gọi tool (SQL, Parallel SQL, Visualization, Report) → viết kết quả vào scratchpad → lặp lại hoặc finalize.
- **Artifact Evaluation** — Mỗi worker output được chuẩn hóa thành `WorkerArtifact`. Artifact Evaluator (deterministic code) quyết định: `continue/retry` → loop back Leader, `wait_for_user` → clarification, `finalize` → output.
- **Capture & Memory** — Capture Action lưu action metadata. Compact & Save Memory quản lý conversation history (PostgreSQL) với auto-compaction. Toàn bộ run được trace JSONL + Langfuse.

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
cd frontend && npm install && npm run dev

# 5. CLI trực tiếp
uv run python -m app.main "Top 5 sản phẩm bán chạy nhất?"
```

| Service | URL |
|---------|-----|
| Frontend UI | http://localhost:3000 |
| FastAPI docs | http://localhost:8001/docs |

---

## Available Tools

Agent exposed **4 high-level tools** qua Leader Agent tool-calling surface:

| Tool | Trigger | What it does |
|------|---------|-------------|
| `ask_sql_analyst` | Data questions, counting, ranking, trend, comparison | Schema lookup → SQL generation → validate → execute → analyze |
| `ask_sql_analyst_parallel` | Multi-part questions (2+ independent sub-queries) | Fan-out parallel SQL workers, merge results |
| `create_visualization` | Inline data values in query (e.g. "vẽ biểu đồ 10, 20, 30") | E2B sandbox → Python/Altair chart |
| `generate_report` | Explicit multi-section report request | 6-phase pipeline: profile → plan → fan-out sections → write → critique → finalize |

**Low-level internals (not exposed to user):**

| Tool | File | Purpose |
|------|------|---------|
| `validate_sql_query` | `app/tools/validate_sql.py` | AST-based SELECT-only validation + regex block |
| `get_schema_overview` | `app/tools/get_schema.py` | Database schema introspection |
| `auto_register_csv` | `app/tools/auto_register.py` | CSV upload → PostgreSQL auto-registration |
| `ConversationMemoryStore` | `app/memory/conversation_store.py` | PostgreSQL conversation persistence |
| `ArtifactStore` | `app/memory/artifact_store.py` | Heavyweight artifact persistence (reports, charts) |

---

## Deployment

- Portfolio demo blueprint: [`docs/deployment/portfolio-demo.md`](docs/deployment/portfolio-demo.md)
- Demo env template: [`.env.example.demo`](.env.example.demo)
- Frontend production demo: https://da-agent-project.vercel.app/

### CI/CD

- **CI:** GitHub Actions chạy backend tests + health/readiness smoke test + frontend lint/typecheck/build
- **Frontend CD:** Vercel tự deploy từ GitHub

### Local vs Production data

- **Local development:** Docker Postgres
- **Production:** Managed Postgres (Neon)
- **Artifact policy:** production artifacts trên container là ephemeral by design cho portfolio demo

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
```

---

## Environment Variables

See [`.env.example`](.env.example) for the full list. Key variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `APP_MODE` | ❌ | `demo` để tắt bớt feature nặng cho bản portfolio |
| `E2B_API_KEY` | ❌ | E2B sandbox (visualization) |
| `ENABLE_LANGFUSE` | ❌ | Langfuse tracing |

> Full env reference: [`docs/ENV.md`](docs/ENV.md)

---

## Project Structure

```
da-agent-project/
├── app/
│   ├── graph/               # LangGraph nodes, state, graph builders
│   │   ├── graph.py         # build_sql_v3_graph() — plan-execute graph
│   │   ├── nodes.py         # leader_agent, artifact_evaluator, capture_action, memory nodes
│   │   ├── task_grounder.py # TaskProfile classifier (LLM mini)
│   │   ├── state.py         # AgentState, TaskProfile, WorkerArtifact, ReportSection
│   │   ├── sql_worker_graph.py  # SQL worker subgraph (gen → validate → execute → analyze)
│   │   ├── report_subgraph.py   # 6-phase report pipeline
│   │   ├── standalone_visualization.py  # E2B sandbox viz worker
│   │   ├── visualization_node.py  # Visualization within SQL worker context
│   │   └── continuity.py   # Follow-up query detection & parameter extraction
│   ├── artifacts/           # Artifact file store helpers
│   ├── memory/              # ConversationMemoryStore (PostgreSQL), ArtifactStore
│   ├── observability/       # RunTracer (JSONL + Langfuse)
│   ├── prompts/             # All LLM prompt definitions
│   ├── tools/               # SQL safety, schema, upload, metadata, table context tools
│   ├── llm/                 # LLM client abstraction
│   ├── utils/               # File hash, misc utilities
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
