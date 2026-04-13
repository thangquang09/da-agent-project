# DA Agent Lab — Project for CV

## Tổng quan

DA Agent Lab là một LangGraph-based Data Analyst Agent prototype, nhận câu hỏi tiếng Việt/tiếng Anh về business data (từ "DAU hôm qua?" đến "So sánh retention cohort rồi vẽ chart"), tự động phân loại query, gọi đúng tool (SQL/RAG/Visualization/Report), và tổng hợp câu trả lời có trích nguồn.

Dự án tồn tại vì tôi muốn học thực tế về agent orchestration — không phải tutorial, không phải hello-world, mà một hệ thống có graph, state, tool-calling loop, và observability thật.

## Technical Stack

- **Orchestration**: LangGraph (`StateGraph`, `add_conditional_edges`, checkpointer)
- **Language**: Python 3.12, `uv` cho dependency management
- **LLM**: OpenAI-compatible API (`gpt-4.1`, `gpt-4o`) qua unified `LLMClient`
- **Data**: PostgreSQL (warehouse + agent memory, schemas: `public` / `agent` / `user_data`), `sqlglot` cho SQL validation
- **Workers**: `ThreadPoolExecutor` cho parallel SQL fan-out, configurable sandbox (Docker / E2B / none) cho visualization/report compute
- **Observability**: Loguru (structured logging), JSONL traces, Langfuse
- **API**: FastAPI + SSE streaming
- **UI**: Next.js 16 (primary, Tailwind + Zustand) + Streamlit (legacy CLI)
- **Testing**: pytest, `monkeypatch`, `conftest.py`
- **Deployment**: Modal (serverless GPU/CPU, `modal deploy`), Docker (`docker/backend.Dockerfile`), CI/CD via GitHub Actions

## Key Contributions

1. **Task Grounder pipeline** — Gọi `gpt-4o-mini` phân loại query thành structured `TaskProfile` (task_mode, data_source, required_capabilities, confidence). Kết quả là leader agent không phải guess context từ đầu; profile được reuse bởi cả leader và artifact_evaluator.
2. **Leader Agent tool-calling loop** — 5 bước max, mỗi bước LLM trả `{action, tool, args}`, code dispatch worker và wrap output thành `WorkerArtifact`. Khi `action="final"` → trả final answer trực tiếp, không qua evaluator.
3. **Artifact Evaluator** — Deterministic code (không phải LLM) evaluate artifacts sau mỗi leader cycle, quyết định `finalize | continue | retry | clarify`. Tách biệt strategic decision (leader) và tactical evaluation (code).
4. **SQL safety validation** — Dùng `sqlglot` parse SQL thành AST, duyệt tree kiểm tra chỉ có `SELECT`/`WITH` (CTE). Regex fallback cho injection patterns. Zero `INSERT`/`UPDATE`/`DELETE`/`DROP` được phép execute.
5. **Parallel SQL execution** — `ask_sql_analyst_parallel` fan-out independent queries qua `ThreadPoolExecutor`, merge results trước khi return.
6. **Observability instrumentation** — Wrapper `_instrument_node` cho mọi node, bind `run_id` vào Loguru context, trace JSONL + Langfuse. Every run có: routing decision, tool calls, generated SQL, latency, errors.

## Architecture Highlights

### Supervisor pattern với LangGraph

Graph có 9 nodes: `START → process_uploaded_files → inject_session_context → task_grounder → leader_agent ↔ artifact_evaluator → [finalize | report_subgraph | clarify] → compact_and_save_memory → END`.

Tôi chọn LangGraph thay vì LangChain Agent vì:

- **Deterministic routing**: Mỗi cạnh trong graph là code, không phải LLM guess. Sau node nào đi đâu, tôi biết chắc.
- **Loop control**: Step counter + artifact_evaluator ngăn agent stuck. Max 5 bước leader, không có "gọi tool ~15 lần" như một số ReAct agent.
- **Typed state**: `AgentState` là `TypedDict`, annotation rõ ràng. Không có magic `agent.state` dict merge.

**Trade-off thật**: Graph có nhiều node hơn LangChain Agent prototype. Mỗi thay đổi flow phải sửa graph builder. Đổi lại, tôi predict được behavior của system.

### Tách strategic vs tactical

Leader agent quyết định **strategy** (gọi tool gì, query gì) — đây là creative work cần LLM. Artifact evaluator quyết định **tactical** (artifact đã đủ chưa, cần retry không) — đây là deterministic logic, không cần LLM.

Đây là design decision quan trọng: LLM không nên control loop termination. Code nên làm việc đó.

## Challenges & Decisions

### Task Grounding — classification ở đâu?

Ban đầu tôi nghĩ classification (SQL vs RAG vs mixed) nên embed trong leader agent. Sau đó tách ra thành Task Grounder riêng với model nhẹ (`gpt-4o-mini`). Lý do:

1. Leader không phải guess context từ đầu mỗi step
2. Model routing — classification rẻ hơn nhiều so với actual execution
3. `task_profile` reusable: leader đọc nó, artifact_evaluator cũng đọc nó để check coverage

### Artifact Evaluator — tại sao không để leader quyết?

Leader hoàn toàn có thể quyết "done" sau khi gọi tool. Nhưng tôi muốn tách biệt:

- Leader quyết định **action** (gọi tool, retry, final)
- Evaluator quyết định **artifact quality** (coverage đủ chưa, có lỗi không)

Điều này giúp debug: nếu agent gọi sai tool, tôi biết là leader decision hay là tool execution có vấn đề.

### SQL Safety — never trust LLM-generated SQL

LLM-generated SQL có thể có syntax errors, wrong table names, hoặc (trong theory) có thể có malicious intent nếu prompt bị injected. Tôi không execute SQL mà không validate qua AST check trước. `sqlglot` parse SQL thành tree, traverse kiểm tra không có mutation operations. Nếu parse fail hoặc detect mutation → reject + log.

## What I Learned

### Về Agent Architecture

Supervisor pattern vs ReAct pattern có trade-off rõ ràng. ReAct flexible hơn cho prototyping nhanh, nhưng khó predict behavior và debug khi agent stuck. Supervisor predictable hơn, nhưng cần define surface trước.

Điều tôi sẽ làm khác: bắt đầu với fewer, broader tools thay vì nhiều narrow tools. Hiện tại 5 tools có thể là over-engineering cho use case hiện tại.

### Về Token Economy

Thực tế implement mới thấy token cost: một simple query tốn ~4,600 tokens (task_grounder + leader + sql_worker + synthesis). Với actual usage, chi phí có thể cao. Đây là lý do tôi thêm model routing — `gpt-4o-mini` cho classification, `gpt-4o` cho actual execution.

Latency cũng quan trọng: E2B sandbox cho visualization startup 5-15s, dominates total latency. Đây là bottleneck thật, và tôi chưa giải quyết triệt để.

### Về Observability

`_instrument_node` wrapper + JSONL traces + Langfuse giúp debug thật sự. Khi có bug, tôi có thể replay một run bằng cách đọc trace. Đây là phần đáng đầu tư nhất — không phải feature mới, mà là debugging capability.

## Deployment

### Infrastructure

- **Backend**: Deploy lên [Modal](https://modal.com) — serverless platform, auto-scale từ 0, không cần manage server. App chạy như một ASGI function (`@modal.asgi_app`) bên trong Docker image được build sẵn trên Modal infrastructure.
- **Frontend**: Next.js 16, deploy riêng (Vercel / static host), point `NEXT_PUBLIC_API_URL` vào Modal endpoint.
- **Database**: PostgreSQL managed (local: Docker Compose, production: managed PG instance). 3 schemas: `public` (user data/warehouse), `agent` (conversation memory, turn artifacts, result store), `user_data` (uploaded CSVs, table business context).

### CI/CD Pipeline (GitHub Actions)

Pipeline 3 jobs, chạy trên mỗi push vào `master`/`main`:

```
push → [backend CI] → [frontend CI] → [deploy-backend (Modal)]
                ↑                ↑
           pytest + health    lint + typecheck + build
           smoke test (uvicorn)
```

1. **backend job**: Spin up PostgreSQL service container, chạy `uv run pytest`, sau đó smoke test `/health` + `/ready` endpoint với uvicorn thật.
2. **frontend job**: `npm ci` → `npm run lint` → `npm run typecheck` → `npm run build`. Build phải pass trước khi deploy.
3. **deploy-backend** (only on push, không chạy trên PR): Chạy sau khi cả 2 job trên pass. Install Modal CLI, authenticate bằng `MODAL_TOKEN_ID` + `MODAL_TOKEN_SECRET` (GitHub secrets), rồi `modal deploy deploy/modal_app.py`.

### Docker Image

`docker/backend.Dockerfile` build image cho Modal:

- Base: `python:3.12-slim`
- Package manager: `uv` (copy từ `ghcr.io/astral-sh/uv:latest`), `uv sync --no-dev --frozen`
- Copy: `app/`, `backend/`, `mcp_server/`, `evals/`, `data/migrations/`, `data/seeds/`, `models.txt`
- Non-root user (`agentuser`) cho security
- Healthcheck: `curl -f http://localhost:8001/health`

### Modal App (`deploy/modal_app.py`)

```python
image = modal.Image.from_dockerfile("docker/backend.Dockerfile", context_dir=PROJECT_ROOT)
app = modal.App("da-agent-demo")

@app.function(image=image, secrets=[modal.Secret.from_name("da-agent-demo-env")])
@modal.asgi_app(label="da-agent-api")
def fastapi_app():
    from backend.main import app as fastapi_app_instance
    return fastapi_app_instance
```

Secrets (API keys, DB URL, LLM keys) được inject qua `modal.Secret` — không hardcode vào image hay repo.

### Lessons learned về deployment

- **Modal `copy_tree` limitation**: Modal's image builder dùng `copy_tree` internaly, fail nếu `COPY` single file (không phải directory). Fix: thay `COPY data/__init__.py` bằng `RUN touch ./data/__init__.py` sau khi copy directory.
- **Demo mode**: `APP_MODE=demo` disable visualization sandbox trong CI vì CI không có Docker-in-Docker. Production dùng `APP_MODE=full` với `TYPE_OF_SANDBOX=docker`.
- **Schema migration on startup**: `ConversationMemoryStore` tự gọi `_ensure_tables()` khi khởi tạo lần đầu, trigger migration tạo `agent` schema. Không cần migration runner riêng.