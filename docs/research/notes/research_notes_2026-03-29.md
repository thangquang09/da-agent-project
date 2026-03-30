# Research Notes - DA Agent (LangGraph)
Date: 2026-03-29

## 1) Scope and method
- Objective: collect practical, interview-relevant LangGraph patterns for a DA Agent (SQL + RAG + Mixed).
- Sources:
  - NotebookLM notebook: `https://notebooklm.google.com/notebook/5220d387-0fa4-4250-8206-435e684c1c0e`
  - Context7 LangGraph Python docs (official docs index)

## 2) NotebookLM MCP execution log (today)
- Initial attempts failed due to browser/profile launch issue (`launchPersistentContext`, `exitCode=21`).
- Recovery executed successfully:
  1. `cleanup_data(confirm=true, preserve_library=true)`
  2. `setup_auth(show_browser=true)`
  3. health verified `authenticated=true`
- Research then proceeded successfully via NotebookLM session: `43b0edad`.

## 3) Findings from NotebookLM (directly from your notebook)

### A. Practical architecture checklist
- Use a typed state with minimal essential fields only.
- Build a dedicated `RouterNode` to classify intent: `sql`, `rag`, `mixed`.
- Keep local-first execution path: Streamlit UI + SQLite + markdown-doc retrieval.
- For `mixed` intent, run SQL and RAG branches then merge in synthesizer.

### B. Tool-contract guidance
- Tool schemas must be explicit and strict (inputs/outputs/errors).
- SQL tool failures should not crash the run; propagate structured errors to state.
- Allow self-correction loop only when error type is retryable.

### C. Prompt strategy guidance
- Separate system prompt (role/rules) from task prompt (question/context).
- Prefer structured outputs for routing and tool args (JSON/enum constraints).
- Inject schema context dynamically for SQL-related tasks.

### D. Observability guidance
- Trace complete run tree (router decision, tool calls, retries, latency).
- Keep component-level logs, not only final input/output.
- Use traces as interview artifacts to explain failure and fix loops.

### E. Evaluation checklist from notebook
- Routing accuracy target: `> 90%`.
- SQL validity target: `> 90%` query success rate.
- SQL result correctness target: `> 85%` against expected outputs.
- Tool-call validity target: `> 95%` valid tool invocations.
- Groundedness target for RAG answers: high factual consistency, no unsupported claims.
- Latency tracking: include TTFT and end-to-end latency budget.

### F. Common failure modes highlighted
- State/context bloat.
- Infinite retry loops.
- Unsafe SQL execution path.
- Ambiguous tool schemas causing bad arguments.
- Router misclassification.
- Missing trace and missing component-level eval.

## 4) LangGraph-specific findings from Context7 docs
Primary library resolved:
- `/websites/langchain_oss_python_langgraph`

Key doc areas queried:
- Graph API (state schema, conditional edges)
- Command/interrupt patterns
- Checkpointing + thread_id persistence
- Retry policies and recursion limit controls

### A. Implementation patterns to adopt
- Define `StateGraph` with explicit `input_schema` and `output_schema`.
- Use conditional edges for stable routing; use `Command(goto=...)` only when needed.
- Enforce `recursion_limit` on each invoke to prevent runaway loops.
- Add node-specific retry policy (DB/tool transient vs validation hard-fail).
- Compile graph with checkpointer and stable `thread_id` for replay/resume.

### B. Safety and deterministic boundaries
- Keep SQL validation deterministic before execution (read-only, table/column checks).
- Separate SQL generation, validation, execution, and analysis into distinct nodes.
- Do not let LLM-only reasoning bypass deterministic safety gates.

## 5) Consolidated recommendations for this repo
- Keep V1 graph compact:
  - `route_intent`
  - `get_schema`
  - `retrieve_context`
  - `generate_sql`
  - `validate_sql`
  - `execute_sql`
  - `analyze_result`
  - `synthesize_answer`
  - `record_trace`
- Add run config contract:
  - `configurable.thread_id`
  - `recursion_limit`
  - `run_id` / trace identifiers
- Keep MCP server minimal in v1: `get_schema`, `query_sql`, `retrieve_metric_definition`.
- Treat eval as release gate for prompt/tool changes.

## 6) Anti-patterns to avoid
- One giant prompt that hides routing and business logic.
- Executing model-generated SQL without deterministic validation.
- No recursion/step budget.
- No trace artifacts for debugging and interview explanation.
- Over-prioritizing UI polish before reliability/eval.

## 7) References
- NotebookLM session: `43b0edad` (notebook URL above)
- LangGraph docs via Context7:
  - https://docs.langchain.com/oss/python/langgraph/use-graph-api
  - https://docs.langchain.com/oss/python/langgraph/graph-api
  - https://docs.langchain.com/oss/python/langgraph/interrupts
  - https://docs.langchain.com/oss/python/langgraph/add-memory
  - https://docs.langchain.com/oss/python/langgraph/persistence
