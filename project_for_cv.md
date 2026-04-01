# DA Agent Lab — Project Portfolio Document

> **For CV / Interview Use · Last Updated: 2026-04-01**

---

## 1. Project Overview

**DA Agent Lab** is a production-ready, multi-agent Data Analytics Engine built on **LangGraph** that translates natural-language business questions into SQL queries and dynamic data visualizations — combining a Text-to-SQL pipeline with secure code execution in E2B cloud sandboxes.
The system features explicit intent routing (SQL / RAG / Mixed), a Plan-and-Execute parallel architecture, self-correcting SQL loops, and a comprehensive observability + evaluation layer designed to make every agent decision traceable, debuggable, and measurable.

---

## 2. Architecture & Frameworks

### Technology Stack

| Layer | Technology |
|---|---|
| **Agent Orchestration** | LangGraph (StateGraph, Send API, Subgraphs) |
| **LLM Providers** | OpenAI GPT-4o / Anthropic Claude (configurable per node) |
| **Dynamic Code Execution** | E2B Cloud Sandbox (`e2b_code_interpreter`) |
| **UI** | Streamlit (multi-turn chat with file upload) |
| **MCP Server** | FastMCP (stdio + streamable-HTTP transports) |
| **Data Warehouse** | SQLite (local-first; adapter pattern for future BigQuery/Snowflake) |
| **RAG** | Custom retriever over markdown business docs |
| **Tracing** | Langfuse (conditional; falls back to in-process tracer) |
| **Logging** | loguru (structured key=value, component-boundary logging) |
| **Testing / Eval** | pytest, custom eval runner with gate thresholds |
| **Packaging** | uv (.venv), Python 3.11+ |

### Multi-Agent Architecture: Supervisor-Worker / Plan-and-Execute

The system ships in two compiled graph versions:

**V1 — Linear Sequential Graph** (stable baseline)
```
User Query
  → detect_context_type   [classifier]
  → process_uploaded_files [tool, conditional]
  → route_intent          [agent]
  ├─ sql/mixed → get_schema → generate_sql → validate_sql ──(retry)──┐
  │                                      ↓                            │
  │                              execute_sql ──(retry)─────────────→ ┘
  │                                      ↓
  │                             analyze_result
  ├─ rag        → retrieve_context_node
  └─ unknown    → synthesize_answer
                         ↓
                  synthesize_answer → END
```

**V2 — Plan-and-Execute Parallel Graph** (production default)
```
User Query
  → detect_context_type
  → process_uploaded_files (conditional)
  → route_intent
  → task_planner            ← decomposes query into N TaskState objects
       ↓ Send API fan-out (parallel)
  ┌────┴────────────────────────────┐
  sql_worker (×N, parallel)    standalone_visualization_worker
    ↓ [subgraph per task]
    get_schema → generate_sql → validate_sql → execute_sql → analyze_result
    └── nested: visualization_node (E2B, conditional)
  └────────────────────────────────┘
       ↓ operator.add fan-in
  aggregate_results
  → synthesize_answer → END
```

**Key architectural pattern:** `route_after_planning()` uses LangGraph's **`Send` API** to dispatch `TaskState` objects to worker subgraphs in true parallel fan-out, then `Annotated[list[TaskState], operator.add]` accumulates results deterministically in `aggregate_results`.

---

## 3. Direct Mapping to Job Description Requirements

### 3.1 AI Application Prototypes & Agents

**What was built:**

- **Full multi-agent LangGraph application** with 12+ nodes wired as a directed graph with conditional edges, retry policies, and subgraphs.
- **Parallel Map-Reduce routing via LangGraph Send API:** `route_after_planning()` in `app/graph/edges.py` creates a list of `Send("sql_worker", task_state)` objects — one per decomposed sub-task — enabling true parallel execution of independent SQL queries with a single fan-in `aggregate_results` node.
- **Text-to-SQL subgraph** (`app/graph/sql_worker_graph.py`): A fully self-contained `StateGraph` that owns its own schema retrieval → SQL generation → validation → execution → analysis pipeline per task. This subgraph is embedded inside the parent V2 graph as a nested worker.
- **Tool-calling agent pattern:** Each tool (`get_schema`, `query_sql`, `validate_sql`, `retrieve_metric_definition`, `retrieve_business_context`, `generate_visualization`) has an explicit input/output contract, making them MCP-compatible from day one.
- **Multi-turn chat with session state** via Streamlit UI backed by LangGraph's `InMemorySaver` checkpointer; each conversation uses a stable `thread_id` for replay and debug.

**Intent routing example (from `app/graph/edges.py`):**
```python
# sql/mixed → task_planner (for parallelization)
# rag       → retrieve_context_node
# unknown   → synthesize_answer (graceful degradation)
def route_to_execution_mode(state: AgentState) -> Literal[...]:
    intent = state.get("intent", "unknown")
    if intent in {"sql", "mixed"}:
        return "task_planner"
    if intent == "rag":
        return "retrieve_context_node"
    return "synthesize_answer"
```

---

### 3.2 Prompt Engineering & LLM Optimization

**What was built:**

#### Two-Tier Data State: Solving Context Window Overload (HTTP 400)

A critical production problem was discovered: passing raw SQL result rows directly into the LLM synthesis prompt caused HTTP 400 errors (context window overflow) on queries returning thousands of rows.

**Solution — Two-tier data state in `AgentState`:**

```python
# Tier 1: Structured data passed to deterministic analysis layer
sql_result: dict  # {rows: list[dict], row_count: int, columns: list[str], latency_ms: float}

# Tier 2: Compressed summary passed to LLM
analysis_result: dict  # {summary: str, trend: str, anomalies: list}
```

The `analyze_result` node performs **deterministic Python analytics** (trend detection, top-K extraction, anomaly checks) and compresses thousands of rows into a concise `analysis_result` dict. The `synthesize_answer` node then receives this compressed summary — never the raw rows — eliminating context overflow completely.

#### Few-Shot Prompting for Structured JSON Output

The `task_planner` node uses **few-shot examples** embedded in the system prompt to force the LLM to output a valid JSON plan with `execution_mode` and `tasks[]` fields. Without few-shot examples, the planner would produce inconsistent JSON structures that broke the `Send` API fan-out. The pattern:

```
System: "You decompose queries into tasks. Output ONLY JSON like this example:
{\"execution_mode\": \"parallel\", \"tasks\": [{\"task_id\": \"t1\", ...}]}"
User: [query + schema]
→ Validated JSON parsed directly into List[TaskState]
```

#### Langfuse Prompt Management Integration

`app/prompts/manager.py` implements a `PromptManager` singleton with:
- **Langfuse-backed versioning** with 300-second TTL cache (A/B testing ready)
- **Local fallback** to hardcoded `PROMPT_DEFINITION` objects when Langfuse is unavailable
- **Variable interpolation** for `{{query}}`, `{{schema_context}}`, `{{#if condition}}` blocks
- **Per-node model routing**: `model_router`, `model_sql_generation`, `model_task_planner`, `model_synthesis` are individually configurable

#### Self-Correction Loop

```python
# SQL Validation failure → self-correction prompt with previous_sql + error
def route_after_sql_validation(state) -> str:
    retry_count = state.get("sql_retry_count", 0)
    if last_error["category"] == "SQL_VALIDATION_ERROR" and retry_count < 2:
        return "generate_sql"   # ← retry with error context injected
    return "execute_sql_node"
```
Same pattern applies at `execute_sql_node` for runtime SQLite errors, with a maximum of 2 retries per run.

---

### 3.3 Agentic Tool Integration (Path to MCP)

**What was built:**

#### E2B Sandbox Integration for Secure Dynamic Code Execution

`app/tools/visualization.py` implements `E2BVisualizationService` — a wrapper around `e2b_code_interpreter.Sandbox` that:

1. **Uploads data as CSV** to an isolated cloud sandbox (`_upload_data()`)
2. **LLM generates matplotlib/seaborn Python code** scoped to the uploaded file path
3. **Executes code** in the E2B sandbox with full network isolation
4. **Extracts PNG/JPEG bytes** from the sandbox output and returns them as base64-encoded image data to Streamlit
5. **Graceful degradation**: if `E2B_API_KEY` is not set, `is_visualization_available()` returns `False` and the entire visualization branch is skipped without crashing

```python
# Conditional import pattern — E2B is fully optional
try:
    from e2b_code_interpreter import Sandbox
    E2B_AVAILABLE = True
except ImportError:
    E2B_AVAILABLE = False
    logger.warning("E2B not installed. Visualization features disabled.")
```

#### Graceful Error Handling: Catching SQLite Column Hallucinations

The most common LLM failure mode in Text-to-SQL is hallucinating column names that don't exist. This was solved in two layers:

**Layer 1 — Pre-execution validation** (`app/tools/validate_sql.py`):
```python
# Extract all table references with regex, then validate against live schema
TABLE_TOKEN_PATTERN = re.compile(r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)\b", ...)
# If referenced table not in schema → SQL_VALIDATION_ERROR → retry
```

**Layer 2 — User-friendly runtime error formatting** (`app/graph/sql_worker_graph.py`):
```python
def _format_sql_error(error_msg: str) -> str:
    if "no such column" in error_lower:
        match = re.search(r"no such column: (\w+)", error_msg)
        column = match.group(1)
        return f"The query references column '{column}' that doesn't exist. Checking columns..."
    # Never leak raw SQLite error messages to the user or LLM synthesis
```

The formatted error is injected into the self-correction prompt so the LLM can fix the exact column name — without the app crashing or the user seeing a raw SQLite traceback.

#### MCP Server (FastMCP)

`mcp_server/server.py` exposes a fully MCP-compatible tool surface over two transports:

| Tool | Description |
|---|---|
| `get_schema(db_path)` | Returns table/column metadata |
| `dataset_context(db_path)` | Returns row counts, date ranges, top values |
| `retrieve_metric_definition(query, top_k)` | RAG over metric docs |
| `query_sql(sql, row_limit, db_path)` | Read-only SQL execution |
| `validate_csv(file_path)` | CSV encoding/delimiter check |
| `profile_csv(file_path)` | Schema + statistical profiling |
| `auto_register_csv(file_path)` | Register CSV as SQLite table |

---

### 3.4 Hardest Technical Challenge: Nested Sequential within Parallel — The Visualization Data Dependency Trap

**The problem:**

In V2's parallel architecture, each `sql_worker` runs independently via the `Send` API. A critical dependency trap emerged: when a task requires visualization, the visualization node needs the **SQL result from the same task** — but in a naive parallel design, these run in separate, isolated branches with no cross-task state sharing.

**Attempted (broken) approach:**
```
task_planner → Send("sql_worker", task) + Send("visualization_worker", task)
                         ↓                              ↓
               [runs in parallel, no SQL result yet] [needs SQL result → fails]
```

**Solution — Nested Sequential Subgraph inside Parallel Fan-out:**

The `sql_worker_graph.py` subgraph embeds the visualization step as the **last sequential node inside the worker**, after SQL execution completes:

```python
# Inside sql_worker_graph (TaskState-scoped, not AgentState)
get_schema → generate_sql → validate_sql → execute_sql → analyze_result
                                                              ↓
                                         [if requires_visualization=True]
                                              visualization_node (E2B)
                                                              ↓
                                              Task complete → fan-in
```

The `TaskState.requires_visualization: bool` flag is set by the task planner based on query intent. This design means:
- SQL and visualization for the **same task** are always sequential (correct dependency order)
- Different tasks still run **in parallel** across the `Send` fan-out
- The `aggregate_results` node extracts `visualization` from the first completed task that has image data

**Code in `edges.py`:**
```python
def route_after_planning(state) -> list[Send] | str:
    sends = []
    for task in task_plan:
        send_state = {
            "task_id": task["task_id"],
            "requires_visualization": task.get("requires_visualization", False),
            ...
        }
        sends.append(Send("sql_worker", send_state))   # ← nested viz happens inside
    return sends
```

This "nested sequential within parallel" pattern is the core architectural insight of V2 and required a full redesign from a flat parallel graph to a hierarchical subgraph model.

---

### 3.5 Data Infrastructure Support

**What was built:**

- **Realistic analytics warehouse** in SQLite: `daily_metrics` (DAU, revenue, retention_d1, avg_session_time), `videos` (watch_time, retention_rate, CTR), `campaigns` (spend, ROAS, installs)
- **CSV auto-registration pipeline** (`app/tools/csv_tools.py`): validate encoding → profile schema → hash-based session cache → register as SQLite table. Hash cache prevents re-processing the same file across multi-turn conversation turns.
- **Dataset context tool** (`app/tools/dataset_context.py`): returns row counts, date ranges, top-N values, and sample rows — injected into SQL generation prompt to reduce hallucinations on unfamiliar tables.
- **`dataset_context_overview`** injected alongside `schema_context` in SQL generation — a two-layer schema awareness system that gives the LLM both structure and statistical profile of the data.

---

## 4. SQL Safety & Read-Only Enforcement

All generated SQL must pass through `validate_sql()` before execution. This is a non-negotiable hard gate:

```python
FORBIDDEN_SQL_PATTERNS = [
    r"\bINSERT\b", r"\bUPDATE\b", r"\bDELETE\b", r"\bDROP\b",
    r"\bALTER\b",  r"\bTRUNCATE\b", r"\bCREATE\b", r"\bREPLACE\b",
    r"\bATTACH\b", r"\bDETACH\b",   r"\bPRAGMA\b",
]
READ_QUERY_PATTERN = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
```

Returns a frozen `SQLValidationResult(is_valid, sanitized_sql, reasons, detected_tables)` — a dataclass that prevents mutation and provides full audit trail.

---

## 5. Observability & Tracing

Every run captures structured telemetry at two levels:

**Run-level** (via `RunTracer` in `app/observability/tracer.py`):
- `run_id`, `thread_id`, `user_query`, `routed_intent`, total latency, token usage, cost estimate, final status

**Node-level** (via `_instrument_node()` decorator in `graph.py`):
```python
def _instrument_node(node_name, fn, observation_type="span"):
    def _wrapped(state):
        tracer = get_current_tracer()
        scope = tracer.start_node(node_name, state, observation_type)
        update = fn(state)
        tracer.end_node(scope, update=update)
        return update
    return _wrapped
```

**Failure taxonomy** (logged as structured error objects in `AgentState.errors`):
`ROUTING_ERROR` · `SQL_GENERATION_ERROR` · `SQL_VALIDATION_ERROR` · `SQL_EXECUTION_ERROR` · `EMPTY_RESULT` · `RAG_RETRIEVAL_ERROR` · `SYNTHESIS_ERROR` · `CSV_PROCESSING_ERROR` · `VISUALIZATION_ERROR` · `STEP_LIMIT_REACHED`

**Langfuse integration** is conditional — enabled by `ENABLE_LANGFUSE=true` with full project/org tagging. Falls back to in-process tracer silently.

---

## 6. Evaluation Framework

`evals/` contains a production-grade eval runner with CI/CD gate thresholds:

```python
GATE_THRESHOLDS = {
    "routing_accuracy":       0.90,
    "sql_validity_rate":      0.90,
    "tool_path_accuracy":     0.95,
    "answer_format_validity": 1.00,
    "groundedness_pass_rate": 0.70,
}
```

**Evaluators implemented:**
- `ExecutionAccuracyEvaluator` — normalized SQL result comparison
- `SpiderExactMatchEvaluator` — Spider NL2SQL benchmark scoring + F1
- `LLMAnswerJudge` — LLM-as-judge for answer quality
- `GroundednessEvaluator` — verifies every factual claim is supported by retrieved/executed data

**Eval case contract** (from `evals/case_contracts.py`):
```json
{
  "id": "case_001",
  "suite": "spider_test",
  "query": "DAU 7 ngày gần đây có giảm không?",
  "expected_intent": "sql",
  "expected_tools": ["get_schema", "generate_sql", "validate_sql", "execute_sql"],
  "expected_context_type": "default",
  "should_have_sql": true,
  "gold_sql": "SELECT date, dau FROM daily_metrics ORDER BY date DESC LIMIT 7",
  "expected_keywords": ["giảm", "7 ngày"]
}
```

The runner uses `ThreadPoolExecutor` for parallel case execution and outputs a comprehensive `CaseResult` dataclass tracking: `routing_correct`, `tool_path_correct`, `sql_valid`, `execution_match`, `groundedness_pass`, `latency_ms`, `answer_quality_score`.

---

## 7. Key Technical Metrics & Outcomes

| Metric | Detail |
|---|---|
| **Context overflow** | Eliminated via Two-Tier Data State (raw rows → compressed `analysis_result`) |
| **SQL hallucination rate** | Reduced via table/column regex pre-validation + 2-retry self-correction loop |
| **Parallel execution** | N independent SQL tasks dispatched simultaneously via `Send` API |
| **Data volume handled** | SQLite queries with LIMIT guardrails; `dataset_context` profiles up to full table statistics |
| **Zero-crash on bad SQL** | `_format_sql_error()` catches all SQLite error classes and returns user-friendly messages |
| **Tool reusability** | All 7 tools work independently of the graph (unit-testable; MCP-exposed) |
| **Eval gate enforcement** | 5 automated thresholds block regressions on routing, SQL validity, and groundedness |
| **Prompt versioning** | Langfuse-backed with 300s TTL cache + local fallback |

---

## 8. State Model Highlights

```python
# app/graph/state.py
class AgentState(TypedDict, total=False):
    # Routing
    intent: Literal["sql", "rag", "mixed", "unknown"]
    context_type: Literal["user_provided", "csv_auto", "mixed", "default"]

    # SQL pipeline
    schema_context: str          # DB structure from get_schema
    dataset_context: str         # Statistical profile from dataset_context tool
    generated_sql: str           # Raw LLM output
    validated_sql: str           # Post-validation, safe to execute
    sql_result: dict             # {rows, row_count, columns, latency_ms}
    sql_retry_count: int         # Self-correction counter (max 2)
    sql_last_error: str | None   # Error injected into self-correction prompt

    # Plan-and-Execute
    task_plan: list[TaskState]
    task_results: Annotated[list[TaskState], operator.add]  # Fan-in accumulator
    execution_mode: Literal["single", "parallel", "linear"]

    # Observability
    tool_history: Annotated[list[dict], operator.add]  # Cumulative across nodes
    errors: Annotated[list[dict], operator.add]        # Structured error log
    run_id: str
```

`GraphInputState` and `GraphOutputState` are separate `TypedDict` classes that scope what enters and exits the graph — preventing accidental state leakage between runs.

---

## 9. Repository Structure (Key Files)

```
app/
  graph/
    state.py                  ← AgentState, TaskState, AnswerPayload, I/O schemas
    nodes.py                  ← 12+ node implementations (~1800 lines)
    edges.py                  ← All routing functions + Send API fan-out
    graph.py                  ← build_sql_v1_graph() + build_sql_v2_graph()
    sql_worker_graph.py       ← Nested subgraph with visualization
    standalone_visualization.py ← E2B-based chart generation for raw data
    visualization_node.py     ← Visualization node for SQL result charts
  tools/
    get_schema.py             ← Schema overview tool
    query_sql.py              ← Read-only SQL executor
    validate_sql.py           ← Regex safety guard + table validator
    dataset_context.py        ← Statistical profiling tool
    visualization.py          ← E2BVisualizationService + VisualizationResult
    retrieve_*.py             ← RAG retrievers (metric definitions + business context)
  prompts/
    manager.py                ← PromptManager (Langfuse + local fallback + TTL cache)
    router.py, sql.py, ...    ← Per-node prompt definitions
  observability/
    tracer.py                 ← RunTracer + LangfuseAdapter + _instrument_node wrapper
    schemas.py                ← Structured trace schemas
  config.py                   ← Settings (Pydantic, env-driven)
  main.py                     ← run_query() entry point

streamlit_app.py              ← Multi-turn chat UI with CSV upload + image rendering
mcp_server/server.py          ← FastMCP server (stdio + HTTP)
evals/
  runner.py                   ← Parallel eval runner + gate thresholds
  metrics.py                  ← ExecutionAccuracy, SpiderExactMatch, LLMJudge, Groundedness
  case_contracts.py           ← EvalCase TypedDict + JSONL loader
  cases.json                  ← Test cases (Spider + MovieLens + business questions)
data/
  warehouse/                  ← SQLite DB with daily_metrics, videos, campaigns
  seeds/create_seed_db.py     ← Deterministic warehouse setup
```

---

## 10. Interview Talking Points

1. **"Why LangGraph over LangChain LCEL or CrewAI?"**
   — Explicit state + conditional edges + subgraphs make every decision traceable. You can inspect exactly which node ran, what it received, what it returned, and why the next node was chosen. CrewAI hides this.

2. **"How did you prevent the LLM from running dangerous SQL?"**
   — Two-layer guard: regex pattern matching against `FORBIDDEN_SQL_PATTERNS` before execution, plus table/column validation against live SQLite schema. Non-negotiable hard gate — the graph cannot reach `execute_sql_node` without passing validation.

3. **"How do you handle a query that returns 50,000 rows?"**
   — The Two-Tier Data State pattern: raw rows go to deterministic `analyze_result` (Python, no LLM), which compresses them to a summary dict. Only the summary enters the synthesis prompt — context overflow eliminated.

4. **"What's the hardest bug you fixed?"**
   — The Visualization Data Dependency Trap: visualization needs data from its sibling SQL task, but parallel branches share no state. Fixed by embedding visualization as the last sequential step inside each worker subgraph — "nested sequential within parallel."

5. **"How do you evaluate this system?"**
   — Behavior-first evaluation: routing accuracy, SQL validity, tool path correctness, groundedness. Gate thresholds block CI if any metric drops below threshold. LLM-as-judge for qualitative answer quality. Spider benchmark for SQL accuracy.

6. **"Is this MCP-compatible?"**
   — Yes from day one. All tools have explicit input/output schemas and are exposed via a FastMCP server over stdio and HTTP transports. The agent can be driven entirely through MCP tool calls.
