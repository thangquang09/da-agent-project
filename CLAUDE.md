# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this repository.

## Documentation rules

> **QUAN TRỌNG — Đọc trước khi bắt đầu làm việc.**

- **CLAUDE.md phải dưới 500 dòng.** Nếu vượt, tách nội dung ra file riêng trong `docs/`.
- **KHÔNG** nhét nội dung chi tiết vào file này. Chỉ giữ tóm tắt + link.
- **Cập nhật docs sau mọi commit tính năng mới.** Code thay đổi → docs thay đổi theo.
  - Tính năng mới / thay đổi → cập nhật `docs/README.md`, `docs/thangquang09/01_architecture.md`, `docs/thangquang09/02_system_design.md` nếu liên quan.
  - Convention mới → cập nhật `docs/CODE_STYLE.md`.
  - Prompt thay đổi → cập nhật `app/prompts/CLAUDE.md`.
  - CLAUDE.md chỉ cập nhật khi có thay đổi về kiến trúc tổng thể, cấu trúc thư mục, hoặc entry points.
- **Không có aspirational docs.** Mọi tài liệu phải đúng với code hiện tại.
- Tư duy code tuyệt đối không được tạo các rule-base ở node quan trọng, bởi vì dự án là ChatBot ngôn ngữ tự nhiên, rule base không thể handle hết trường hợp và rất dễ dẫn tới các bugs fallback.

> **Docs entry point**: `docs/README.md` — mục lục chi tiết của toàn bộ documentation.

---

## Project

**DA Agent Lab** — A LangGraph-based Data Analyst Agent.

Trả lời business/data questions qua SQL tools, Visualization, Report generation, và full observability.

- **Runtime**: `uv` virtualenv (`.venv`)
- **Database**: PostgreSQL (schemas: `public`, `agent`, `user_data`)
- **LLM orchestration**: LangGraph (10-node graph, 3 routing decisions)
- **Frontend**: Next.js web chat (:3000) + Streamlit UI (:8501) → FastAPI backend
- **Sandboxing**: Configurable `docker | e2b | none` for visualization/report compute, default `docker`
- **Observability**: JSONL traces + Langfuse

---

## Skills

- `context7` — Look up latest API documentation of libraries.
- `langgraph` — `.codex/skills/mastering-langgraph/SKILL.md`
- `nlm` (NotebookLM) — `.agents/skills/nlm-skill/SKILL.md` — Notebook `LLM - KD - AI AGENT` cho kiến thức về LLMs, Agents, MCP.
- `langfuse` — `.agents/skills/langfuse/SKILL.md` — Agent tracing with Langfuse.

---

## Quick reference — Dev commands

```bash
# Run (Backend + Frontend)
uv run uvicorn backend.main:app --port 8001 --reload     # Backend API
BACKEND_URL=http://localhost:8001 uv run streamlit run streamlit_app.py  # Streamlit UI
uv run python -m app.main "Top 5 sản phẩm bán chạy?"      # CLI direct

# Frontend (Next.js — primary UI)
cd frontend && npm run dev                                 # Dev server at :3000
cd frontend && npm run build && npm start                  # Production build

# Test
uv run pytest                                              # All tests
uv run pytest tests/test_sql_tools.py -v                   # Single file
uv run pytest -k "memory" -v                               # Pattern match
uv run pytest --cov=app --cov-report=term-missing           # Coverage

# Eval
uv run python evals/runner.py                              # Full eval suite

# Data
PYTHONPATH=. python data/seeds/create_seed_db.py           # Seed database

# Docker
docker compose up -d                                       # Start infra
docker exec da-agent-postgres psql -U postgres -c "\dt"    # List tables
```

| Service | URL |
|---------|-----|
| Next.js UI (primary) | http://localhost:3000 |
| Streamlit UI (legacy) | http://localhost:8501 |
| FastAPI docs | http://localhost:8001/docs |
| MCP server | http://localhost:8000/mcp |

---

## Architecture overview

```text
User (Next.js / Streamlit / CLI / API)
        |
        v
  FastAPI Backend (:8001)
        |
        v
  LangGraph StateGraph (10 nodes)
        |
        +-- process_uploaded_files  →  Parse + register tables
        +-- inject_session_context  →  Load conversation history
        +-- task_grounder           →  LLM mini: TaskProfile (mode, source, capabilities, confidence)
        +-- leader_agent            →  Tool routing with deterministic report dispatch
        +-- artifact_evaluator     →  Deterministic: finalize / continue / retry / wait_for_user
        +-- clarify_question_node  →  Interrupt: halt if confidence=low or mode=ambiguous
        +-- capture_action_node    →  Save last_action, conversation_turn
        +-- compact_and_save_memory →  Persist to PostgreSQL (agent schema)
        +-- report_subgraph        →  8-node Send() pipeline: profiler_sampler → profiler_analyzer → report_planner → [Send fan-out section_pipeline] → sections_sort → report_writer → report_critic → report_finalize
        v
  Synthesized answer + trace (JSONL + Langfuse)
```

**Worker tools** (internal, not exposed to user):

| Tool | File | Purpose |
|------|------|---------|
| `ask_sql_analyst` | `app/tools/` | Schema → SQL → validate → execute → analyze |
| `ask_sql_analyst_parallel` | `app/tools/` | Fan-out parallel SQL workers |
| `create_visualization` | `app/graph/standalone_visualization.py` | Configurable sandbox → chart artifact (saved to `artifacts/`, URL in state) |
| `generate_report` | `app/graph/report_subgraph.py` | Grounded report pipeline: sample → profile → plan → [Send fan-out section_pipeline] → sort → write → critique → finalize |
| `validate_sql_query` | `app/tools/validate_sql.py` | AST-based SELECT-only validation |
| `get_schema_overview` | `app/tools/get_schema.py` | DB schema introspection |
| `table_metadata` | `app/tools/table_metadata.py` | Persist business context per table (`user_data.table_contexts`) |

---

## Core principles

1. **Constrained agent** — LLM decides, tools execute, deterministic code analyzes.
2. **Observability-first** — Each run captured: run_id, routing, tools, SQL, latency, errors. Replayable.
3. **SQL safety** — Only `SELECT` / CTE allowed. Block: `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, etc. Validate before execute.
4. **Evaluation-driven** — Measure routing, SQL validity, tool-call correctness, answer quality. Run regression after every change.
5. **Grounded answers** — No hallucinated numbers. Distinguish DB data vs explicit business context vs inference.

### Routing behavior

| Query type | Intent | Example |
|-----------|--------|---------|
| Hỏi giá trị, ranking, trend | `sql` | "DAU hôm qua?" |
| Cần cả data lẫn chart / nhiều bước phân tích | `mixed` | "Doanh thu giảm từ ngày nào và vẽ biểu đồ xu hướng" |
| Cần báo cáo dài, nhiều section, có biểu đồ | `report` | "Viết báo cáo chi tiết về bộ data này" |

Route bằng structured output (enum), không phải free-form text.

### Data panel — business context

- Users upload CSVs via the Data Panel (`/data/upload`). Table names are normalized (hyphens/spaces → underscores).
- After upload, users can attach **business context** per table (e.g. "Titanic passenger survival data from 1912").
- Context is persisted in `user_data.table_contexts` (Postgres) and merged into the agent's XML database context at query time via `_get_merged_table_contexts()`.
- API: `PUT /data/tables/{name}/context`, `DELETE /data/tables/{name}`, `GET /data/tables` (includes `business_context` field).

### Report grounding

- Report requests are normalized to `required_capabilities=["report"]` and dispatched directly into `report_subgraph`.
- **Phase 1 (profiler_sampler)**: Runs `SELECT * FROM table ORDER BY RANDOM() LIMIT 100` + column stats (min/max/unique/nulls), caps at 2 tables, 15 cols/table. Filters out system tables.
- **Phase 2 (profiler_analyzer)**: LLM analyzes schema + sample data + business context to produce domain summary and suggest 3-5 report sections.
- **Phase 3 (report_planner)**: Uses profiler suggestions directly (or falls back to LLM call) to build `ReportPlan` with `domain_context`.
- **Phase 4 (section_pipeline via Send())**: Fan-out: each section independently runs SQL → sandbox (compute_stats + chart) → insight generation. Single sandbox instance reused. Results accumulate via `_report_sections_raw` with `operator.add` reducer.
- **Phase 5 (sections_sort)**: Reassembles sections in original planner order after fan-in using `section_order` field.
- **Phase 6 (report_writer)**: Synthesizes Executive Summary + Recommendations from grounded insights.
- **Phase 7 (report_critic)**: Validates numeric claims; routes back to writer (max 2 revisions) or to finalize.
- **Phase 8 (report_finalize)**: Packages final markdown + section payloads for frontend.
- Insight nodes can inspect chart images for qualitative reasoning, but every numeric claim must come from `computed_stats.json`.
- Final chat answer for report mode is intentionally short; the full document and section charts are rendered in the right-side Report artifact panel.

---

## Implementation priorities

1. Correctness
2. Observability
3. Evaluation
4. Clarity of architecture
5. Feature expansion
6. UI polish

---

## Non-goals (early versions)

- Polished enterprise UI
- Multi-tenant auth / production infra / large-scale deployment
- Premature multi-agent complexity
- Over-engineered microservices

---

## Code conventions

- **Logging**: `loguru` only, structured placeholders, never log secrets.
- **Imports**: `from __future__ import annotations` first, grouped (stdlib → third-party → local).
- **Types**: modern `|` union syntax, `TypedDict` for state, `Literal` for enums.
- **Naming**: files `snake_case`, classes `PascalCase`, constants `SCREAMING_SNAKE_CASE`.
- **Testing**: `pytest` + `monkeypatch` + `conftest.py` fixtures.

> **Chi tiết đầy đủ**: `docs/CODE_STYLE.md`

---

## Available tools

| Tool | Purpose |
|------|---------|
| GitHub MCP | Search public code references |
| NotebookLM MCP | `https://notebooklm.google.com/notebook/5220d387-0fa4-4250-8206-435e684c1c0e` — LLM/Agent knowledge |

---

## Project purpose & interview value

Dự án này là **applied AI portfolio project** cho vị trí AI/Agent Engineer. Mapping với:
- AI application prototyping, tool-calling agents, SQL-first analytics pipelines
- Prompt design, MCP-style tool surfaces
- SQL/data infrastructure, evaluation, observability

Khi đánh giá một change, tự hỏi:

> *"Change này có giúp system dễ explain, debug, evaluate, và defend trong interview không?"*

Có → good change. Không → probably a distraction.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | `postgresql://postgres:postgres@localhost:5432/postgres` | PostgreSQL |
| `LLM_API_URL` | Yes | — | LLM API endpoint |
| `LLM_API_KEY` | Yes | — | API key |
| `TYPE_OF_SANDBOX` | No | `docker` | Sandbox backend for visualization/report compute: `docker`, `e2b`, or `none` |
| `DOCKER_SANDBOX_IMAGE` | No | `da-agent-sandbox:latest` | Docker image used for sandbox execution |
| `DOCKER_SANDBOX_BASE_IMAGE` | No | `python:3.11-slim` | Base image used when bootstrapping the Docker sandbox image |
| `E2B_API_KEY` | No | — | E2B sandbox key when `TYPE_OF_SANDBOX=e2b` |
| `BACKEND_URL` | No | `http://localhost:8001` | Streamlit → Backend |
| `ENABLE_LANGFUSE` | No | `false` | Langfuse tracing |
| `ARTIFACT_ROOT` | No | `./artifacts` | Root directory for file-based artifact storage (PNG charts, report markdown) |

> **Chi tiết đầy đủ**: `docs/ENV.md`

---

## Documentation map

| File | Purpose |
|------|---------|
| `CLAUDE.md` (this file) | Agent entry point — summary, commands, principles |
| `docs/README.md` | **Full documentation index** — architecture, tech specs, conventions |
| `docs/thangquang09/` | Tiếng Việt — architecture, system design, interview Q&A, CV |
| `docs/_tech_specs/` | English — state model, worker contracts, observability |
| `docs/CODE_STYLE.md` | Code conventions |
| `docs/ENV.md` | Environment configuration |
| `docs/RUNBOOK.md` | Production operational guide |
| `docs/mcp/` | MCP server documentation |
| `app/prompts/CLAUDE.md` | Prompt inventory — all LLM prompts defined here |
| `frontend/CLAUDE.md` | Frontend (Next.js) architecture and commands |

### Reading by role

| Role | Read |
|------|------|
| Phỏng vấn viên | `docs/thangquang09/01_architecture.md` + `03_interview_qna.md` |
| Review code mới | `docs/_tech_specs/01_state_model.md` + `02_worker_contracts.md` |
| Debug production | `docs/_tech_specs/03_observability.md` |
| Thay đổi kiến trúc | `docs/_tech_specs/01_state_model.md` → `02_worker_contracts.md` |

### Source of truth

- **Graph flow**: `app/graph/graph.py` → `build_sql_v3_graph()`
- **State model**: `app/graph/state.py` → `AgentState`, `TaskProfile`, `WorkerArtifact`
- **Nodes**: `app/graph/nodes.py`
- **Observability**: `app/observability/tracer.py`
- **Prompts**: `app/prompts/task_grounder.py`, `app/prompts/leader.py`, `app/prompts/report_data_profiler.py`
- **Frontend**: `frontend/` — Next.js 16 + Tailwind + Zustand
