# Observability: Tracing System

> Source: `app/observability/tracer.py`, `app/graph/graph.py`

## Overview

The tracing system captures every node execution with latency, input/output summaries, and error metadata. It writes to both JSONL files (for replay) and Langfuse (for UI).

---

## RunTracer

Main tracing class. Thread-safe via `threading.Lock`.

### Constructor

```python
class RunTracer:
    def __init__(
        self,
        run_id: str,
        thread_id: str,
        query: str,
        trace_path: Path | None = None,
    ) -> None:
        self.run_id = run_id
        self.thread_id = thread_id
        self.query = query
        self.started_at = utc_now_iso()
        self.started_perf = time.perf_counter()
        self.node_attempts: Counter[str]  # Tracks retries per node
        self.node_records: list[NodeTraceRecord]  # In-memory buffer
        self.langfuse = LangfuseAdapter()  # Optional Langfuse integration
```

### Key Methods

| Method | Purpose |
|--------|---------|
| `start_node(node_name, state, observation_type)` | Begin node span, returns `NodeScope` |
| `end_node(scope, update, error)` | End span, write JSONL, update Langfuse |
| `finish(payload, status, error_message)` | Finalize run, write `RunTraceRecord` |

---

## `_instrument_node()`

**File:** `app/graph/graph.py` lines 22–44

Decorator factory that wraps every node:

```python
def _instrument_node(node_name: str, fn, observation_type: str = "span"):
    def _wrapped(state: AgentState) -> AgentState:
        tracer = get_current_tracer()
        with logger.contextualize(run_id=..., node_name=node_name, ...):
            if tracer is None:
                return fn(state)
            scope = tracer.start_node(node_name=node_name, state=state,
                                       observation_type=observation_type)
            try:
                update = fn(state)
            except Exception as exc:
                tracer.end_node(scope, error=exc)
                raise
            tracer.end_node(scope, update=update)
            return update
    return _wrapped
```

### Instrumentation Points

```python
builder.add_node("process_uploaded_files",
    _instrument_node("process_uploaded_files", process_uploaded_files, "tool"))
builder.add_node("task_grounder",
    _instrument_node("task_grounder", task_grounder, "agent"))
builder.add_node("leader_agent",
    _instrument_node("leader_agent", leader_agent, "agent"))
builder.add_node("artifact_evaluator",
    _instrument_node("artifact_evaluator", artifact_evaluator, "agent"))
```

### Observation Types

| Type | Used By |
|------|---------|
| `"span"` | Default (generic) |
| `"tool"` | Worker tool calls |
| `"agent"` | LLM-driven nodes |
| `"retriever"` | RAG retrieval |
| `"generation"` | LLM generation |
| `"chain"` | Aggregation nodes |

---

## `_run_traced_substep()`

**File:** `app/graph/nodes.py` lines 1200–1230

Traces sub-components inside a node (parallel tasks, LLM calls):

```python
def _run_traced_substep(
    node_name: str,
    state: dict[str, Any],
    fn: Callable[[], Any],
    observation_type: str = "tool",
    tracer_override: RunTracer | None = None,
    update_for_trace: dict[str, Any] | None = None,
) -> Any:
    tracer = tracer_override or get_current_tracer()
    scope = tracer.start_node(node_name=node_name, state=state,
                              observation_type=observation_type)
    try:
        update = fn()
    except Exception as exc:
        tracer.end_node(scope, error=exc)
        raise
    tracer.end_node(scope, update=traced_update)
    return update
```

### Usage in leader_agent

```python
result = _run_traced_substep(
    "leader_sql_task_1",
    trace_state,
    lambda: ask_sql_analyst_tool(state, query),
    observation_type="tool",
    tracer_override=tracer,
)
```

---

## State Summarization

### `_state_summary()`

Extracts key fields for trace input:

```python
def _state_summary(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_query": state.get("user_query"),
        "task_id": state.get("task_id"),
        "step_count": state.get("step_count"),
        "task_profile": _safe_jsonable(state.get("task_profile")),
        "artifact_count": len(state.get("artifacts", [])),
        "has_schema_context": bool(state.get("schema_context")),
        "generated_sql": _safe_jsonable(state.get("generated_sql")),
        "validated_sql": _safe_jsonable(state.get("validated_sql")),
        "sql_row_count": state.get("sql_result", {}).get("row_count"),
        "retrieved_context_count": len(state.get("retrieved_context", [])),
        "errors": _safe_jsonable(state.get("errors", [])),
    }
```

### `_output_summary()`

Extracts key fields for trace output:

```python
def _output_summary(update: dict[str, Any]) -> dict[str, Any]:
    return {
        "keys": sorted(list(update.keys())),
        "answer_preview": update.get("final_answer"),
        "intent": update.get("intent"),
        "step_count": update.get("step_count"),
        "status": update.get("status"),
        "sql_row_count": update.get("sql_result", {}).get("row_count"),
        "tool_history_delta": len(update.get("tool_history", [])),
        "generated_sql": _safe_jsonable(update.get("generated_sql")),
        "artifact_type": update.get("artifact_type"),
        "terminal": update.get("artifact_terminal"),
        "recommended_action": update.get("artifact_recommended_action"),
    }
```

### `_safe_jsonable()`

Truncates large values for safe JSON serialization:

```python
def _safe_jsonable(value: Any, max_length: int = 300) -> Any:
    if isinstance(value, str):
        return value[:max_length] + ("..." if len(value) > max_length else "")
    if isinstance(value, dict):
        out = {}
        for idx, (k, v) in enumerate(value.items()):
            if idx >= 12:  # Max 12 keys
                out["..."] = "truncated"
                break
            out[str(k)] = _safe_jsonable(v, max_length=max_length)
        return out
    # ... handles list, int, float, bool, None
```

---

## JSONL Trace Format

Traces are written to `{trace_jsonl_path}/{run_id}.jsonl` (default: `./traces/{run_id}.jsonl`).

### Run Record (one per run)

```json
{
  "record_type": "run",
  "run_id": "abc123",
  "thread_id": "session-1",
  "started_at": "2026-04-05T10:30:00Z",
  "ended_at": "2026-04-05T10:30:05Z",
  "latency_ms": 5000.0,
  "query": "What is DAU today?",
  "intent": "sql",
  "status": "success",
  "total_steps": 4,
  "used_tools": ["ask_sql_analyst", "retrieve_rag_answer"],
  "generated_sql": "SELECT ...",
  "retry_count": 1,
  "fallback_used": false,
  "error_categories": [],
  "total_token_usage": 1500,
  "total_cost_usd": 0.0025,
  "final_confidence": "high",
  "task_profile": {"task_mode": "simple", "data_source": "database"},
  "grounding_confidence": "high",
  "artifact_count": 2,
  "artifact_types": ["sql_result", "rag_context"]
}
```

### Node Record (one per node invocation)

```json
{
  "record_type": "node",
  "run_id": "abc123",
  "node_name": "leader_agent",
  "attempt": 1,
  "status": "ok",
  "started_at": "2026-04-05T10:30:00Z",
  "ended_at": "2026-04-05T10:30:03Z",
  "latency_ms": 3000.0,
  "input_summary": {"user_query": "...", "step_count": 0},
  "output_summary": {"keys": [...], "status": "ok"},
  "observation_type": "agent"
}
```

### Error Record

On error, `status` is `"error"` and these fields are added:

```json
{
  "error_category": "SQL_VALIDATION_ERROR",
  "error_message": "Unknown table(s): nonexistent_table"
}
```

---

## Langfuse Integration

`LangfuseAdapter` wraps Langfuse SDK with graceful fallback.

### Initialization

```python
class LangfuseAdapter:
    def __init__(self) -> None:
        self.enabled = False
        if not self.settings.enable_langfuse:
            return
        # Checks LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
        self.client = get_client()
        self.enabled = True
```

### Methods

| Method | Langfuse Call |
|--------|---------------|
| `start_run(run_id, query, thread_id)` | `start_observation(as_type="agent")` |
| `start_node(parent, node_name, state, obs_type)` | `parent.start_observation()` |
| `end_node(node_obs, update, error_message)` | `node_obs.update(...).end()` |
| `end_run(payload, status, error_message)` | `root.update(...).end(); flush()` |

### Prompt Versioning

Prompts are versioned in Langfuse via `PromptManager`:

```python
prompt = langfuse_client.get_prompt(
    "router",
    type="chat",
    fallback=messages,  # Local fallback if Langfuse unavailable
    labels=["production"],
)
compiled = prompt.compile(**variables)
```

### Fallback Behavior

If Langfuse credentials are missing or SDK fails, `enabled = False` and all calls become no-ops. Traces still write to JSONL.

---

## ContextVar for Tracer Access

Thread-local storage so any function in the call stack can access the tracer:

```python
_CURRENT_TRACER: ContextVar["RunTracer | None] = ContextVar("run_tracer", default=None)

def get_current_tracer() -> RunTracer | None:
    return _CURRENT_TRACER.get()

def set_current_tracer(tracer: RunTracer | None) -> Token:
    return _CURRENT_TRACER.set(tracer)

def reset_current_tracer(token: Token) -> None:
    _CURRENT_TRACER.reset(token)
```

Usage in `app/main.py`:

```python
tracer = RunTracer(run_id=run_id, thread_id=thread_id, query=query)
token = set_current_tracer(tracer)
try:
    result = graph.invoke(input_state)
finally:
    tracer.finish(payload=result, status="success")
    reset_current_tracer(token)
```

---

## Debug Mode: What Gets Logged

| Field | Notes |
|-------|-------|
| `run_id` | Auto-generated UUID, logged to every trace line |
| `node_name` | Current node, via `logger.contextualize` |
| `task_id` | Per-task identifier |
| `user_query` | Truncated for privacy |

### Log Filtered Fields

These are NEVER logged (excluded from traces):
- Full SQL results (only `row_count` is logged)
- `uploaded_file_data` content
- Session memory content beyond summary

### Replay Support

JSONL traces enable replay by extracting:
1. `run_id` + `thread_id` for re-attach
2. `node_name` + `attempt` for step matching
3. `input_summary` for state reconstruction
