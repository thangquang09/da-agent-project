# Observability Schema Reference

> Source: `app/observability/schemas.py`, `app/observability/tracer.py`

## Schema Definitions

### `NodeTraceRecord`

Emitted once per node invocation (including retries).

```python
@dataclass
class NodeTraceRecord:
    record_type: str                    # Always "node"
    run_id: str                         # UUID from graph invocation
    node_name: str                      # e.g., "leader_agent", "task_grounder"
    attempt: int                         # Retry count (1-indexed)
    status: Literal["ok", "error"]
    started_at: str                     # ISO 8601 UTC timestamp
    ended_at: str                       # ISO 8601 UTC timestamp
    latency_ms: float                    # Calculated: ended - started (perf_counter)
    input_summary: dict[str, Any]        # Key fields from state at entry
    output_summary: dict[str, Any]       # Key fields from node output
    error_category: str | None           # Failure type (see below)
    error_message: str | None            # Exception string
    observation_type: str = "span"       # Span classification
```

### `RunTraceRecord`

Emitted once per graph invocation (run).

```python
@dataclass
class RunTraceRecord:
    record_type: str                    # Always "run"
    run_id: str
    thread_id: str
    started_at: str                     # Set in RunTracer.__init__
    ended_at: str                       # Set in RunTracer.finish
    latency_ms: float
    query: str                          # Original user query
    intent: str                         # Resolved intent
    status: Literal["success", "failed"]
    total_steps: int                    # step_count at completion
    used_tools: list[str]               # Tool names from tool_history
    generated_sql: str
    retry_count: int                    # Sum of (attempts - 1) across all nodes
    fallback_used: bool                  # True if any fallback triggered
    error_categories: list[str]
    total_token_usage: int | None
    total_cost_usd: float | None
    final_confidence: str | None
    # v4 Grounding fields
    task_profile: dict[str, Any] | None  # TaskProfile JSON
    grounding_confidence: str | None     # Confidence from grounder
    # v4 Artifact tracking
    artifact_count: int = 0
    artifact_types: list[str] = field(default_factory=list)
```

---

## Error Categories

Defined in `tracer.py`:

```python
NODE_TO_FAILURE = {
    "route_intent": "ROUTING_ERROR",
    "generate_sql": "SQL_GENERATION_ERROR",
    "validate_sql_node": "SQL_VALIDATION_ERROR",
    "execute_sql_node": "SQL_EXECUTION_ERROR",
    "retrieve_context_node": "RAG_RETRIEVAL_ERROR",
    "synthesize_answer": "SYNTHESIS_ERROR",
}

FailureCategory = Literal[
    "ROUTING_ERROR",
    "SQL_GENERATION_ERROR",
    "SQL_VALIDATION_ERROR",
    "SQL_EXECUTION_ERROR",
    "EMPTY_RESULT",
    "RAG_RETRIEVAL_ERROR",
    "RAG_IRRELEVANT_CONTEXT",
    "SYNTHESIS_ERROR",
    "STEP_LIMIT_REACHED",
]
```

---

## RunTracer Methods

### `start_node()`

```python
def start_node(
    self,
    node_name: str,
    state: dict[str, Any],
    observation_type: str = "span",
) -> NodeScope:
```

**Behavior:**
1. Increments `node_attempts[node_name]`
2. Creates `NodeScope` with timestamp + input summary
3. Calls `langfuse.start_node()` if enabled
4. Returns `NodeScope` for later `end_node()`

### `end_node()`

```python
def end_node(
    self,
    scope: NodeScope,
    update: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> None:
```

**Behavior:**
1. Calculates `latency_ms` from `scope.started_perf`
2. Maps `node_name` → `error_category` via `NODE_TO_FAILURE`
3. Creates `NodeTraceRecord` with input + output summaries
4. Appends to `node_records` (in-memory)
5. Writes to JSONL via `_append_jsonl()`
6. Calls `langfuse.end_node()` if enabled

### `finish()`

```python
def finish(
    self,
    payload: dict[str, Any],
    status: str = "success",
    error_message: str | None = None,
) -> None:
```

**Behavior:**
1. Calculates total run latency
2. Aggregates token usage + cost from `tool_history`
3. Infers error categories: `EMPTY_RESULT`, `RAG_IRRELEVANT_CONTEXT`, `STEP_LIMIT_REACHED`
4. Counts retries from `node_attempts`
5. Extracts `artifact_types` from `payload.artifacts`
6. Creates `RunTraceRecord` and writes to JSONL
7. Calls `langfuse.end_run()` if enabled

### `_append_jsonl()`

```python
def _append_jsonl(self, record: dict[str, Any]) -> None:
    with self.trace_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
```

Writes one JSON object per line. Thread-safe via `self._lock`.

---

## `utc_now_iso()`

```python
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
```

Used for all timestamps in trace records.

---

## NodeScope (Internal)

```python
@dataclass
class NodeScope:
    node_name: str
    attempt: int
    started_at: str              # ISO timestamp
    started_perf: float           # time.perf_counter() value
    input_summary: dict[str, Any] # Snapshot of state at entry
    observation_type: str
    langfuse_observation: Any = None  # Langfuse handle
```

Returned by `start_node()`, consumed by `end_node()`.

---

## Tracing Context Lifecycle

```
graph.invoke(input)
  │
  ├─► RunTracer(run_id, thread_id, query)
  │     ├─► langfuse.start_run()
  │     └─► set_current_tracer(tracer)  [ContextVar]
  │
  ├─► graph execution (nodes call get_current_tracer())
  │     │
  │     ├─► _instrument_node wrapping each node
  │     │     ├─► tracer.start_node() → NodeScope
  │     │     ├─► fn(state) → update
  │     │     └─► tracer.end_node(scope, update)
  │     │
  │     └─► _run_traced_substep() for sub-components
  │
  ├─► tracer.finish(payload)
  │     └─► langfuse.end_run()
  │
  └─► reset_current_tracer(token)
```

---

## JSONL Line Format

Each line is a flat JSON object. Records are distinguishable by `record_type`:

```jsonl
{"record_type":"run","run_id":"...","...":"..."}
{"record_type":"node","run_id":"...","...":"..."}
{"record_type":"node","run_id":"...","...":"..."}
{"record_type":"run","run_id":"...","...":"..."}
```

All records for a run share the same `run_id`.

---

## Key Field Transformations

| Input Field | Output Summary Key | Notes |
|-------------|-------------------|-------|
| `sql_result.rows` | `sql_row_count` | Only count, not rows |
| `tool_history` | `tool_history_delta` | Count of new entries |
| `errors` | `errors_delta` | Count of new entries |
| `artifacts` | `artifact_type`, `terminal`, `recommended_action` | First artifact only |
| `final_answer` | `answer_preview` | Truncated to 300 chars |

---

## Integration Points

| File | Usage |
|------|-------|
| `app/main.py` | Creates `RunTracer`, calls `finish()` |
| `app/graph/graph.py` | `_instrument_node()` wraps all nodes |
| `app/graph/nodes.py` | `_run_traced_substep()` for sub-components |
| `app/graph/report_subgraph.py` | Separate `_instrument_node()` |
| `app/prompts/manager.py` | Langfuse prompt versioning |
