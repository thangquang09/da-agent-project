# Worker Contracts

> Source: `app/graph/nodes.py`, `app/graph/standalone_visualization.py`, `app/graph/report_subgraph.py`

Workers are stateless functions invoked by `leader_agent`. Each returns a `dict` with standard fields plus `WorkerArtifact`-prefixed fields for the supervisor/evaluator.

---

## `ask_sql_analyst_tool()`

**File:** `app/graph/nodes.py` lines 1233–1388

### Signature

```python
def ask_sql_analyst_tool(
    state: AgentState,
    query: str,
    *,
    allow_decomposition: bool = True,
) -> dict[str, Any]
```

### Input

| Field | Source | Notes |
|-------|--------|-------|
| `state` | Parent `AgentState` | Used to extract: `target_db_path`, `schema_context`, `session_context`, `xml_database_context`, `table_contexts`, `last_action`, `thread_id`, `run_id` |
| `query` | `str` | User's SQL question |
| `allow_decomposition` | `bool` | If `True` and query is multi-part, calls `task_planner` for parallelization |

### Processing

1. If `allow_decomposition` and `_should_decompose_sql_query(query)` → calls `task_planner`
2. Parallel execution via `ThreadPoolExecutor(max_workers=4)` if multiple tasks
3. Calls `_execute_sql_analyst_task` per task (subgraph: generate → validate → execute → analyze)
4. If single task → generates natural language answer via `_generate_natural_response`
5. If multiple tasks → calls `aggregate_results` for fan-in

### Returns

```python
{
    # Execution result
    "status": "ok" | "failed",
    "task_count": int,
    "execution_mode": "linear" | "parallel",
    "answer_summary": str,
    "sql_result": {"rows": list, "row_count": int, "columns": list},
    "generated_sql": str,
    "validated_sql": str,
    "result_ref": dict | None,
    "visualization": dict | None,
    "tool_history": list[dict],
    "errors": list[dict],
    "confidence": Confidence,

    # WorkerArtifact fields (for artifact_evaluator)
    "artifact_type": "sql_result",
    "artifact_status": "success" | "partial" | "failed",
    "artifact_payload": {
        "sql_result": dict,
        "answer_summary": str,
    },
    "artifact_evidence": {
        "generated_sql": str,
        "validated_sql": str,
        "table": str,  # Extracted from SQL
    },
    "artifact_terminal": bool,  # True if all tasks succeeded
    "artifact_recommended_action": "finalize" | "retry_sql" | "clarify",
}
```

### Error Categories

```python
{
    "category": "SQL_ANALYST_ERROR",
    "message": str,
    "task_id": str | None,
}
```

---

## `ask_sql_analyst_parallel_tool()`

**File:** `app/graph/nodes.py` lines 1391–1532

### Signature

```python
def ask_sql_analyst_parallel_tool(
    state: AgentState,
    tasks: list[dict[str, str]],
    parent_query: str,
) -> dict[str, Any]
```

### Input

| Field | Type | Notes |
|-------|------|-------|
| `tasks` | `list[dict]` | Each: `{task_id, query, type}` |
| `parent_query` | `str` | Original user query for context |
| `state` | `AgentState` | Parent state for context |

### Processing

1. Normalizes task structure via `_normalize_parallel_sql_tasks`
2. Dispatches each task to `ask_sql_analyst_tool` with `allow_decomposition=False`
3. Runs in parallel via `_dispatch_parallel_sql_tasks`
4. Fan-in via `aggregate_results`
5. Returns `task_results: list[dict]` for each subtask

### Returns

Same shape as `ask_sql_analyst_tool` plus:

```python
{
    "task_results": [
        {
            "task_id": str,
            "query": str,
            "status": "success" | "failed",
            "sql_result": dict,
            "generated_sql": str,
            "validated_sql": str,
            "result_ref": dict | None,
            "visualization": dict | None,
            "error": str | None,
            "tool_history": list[dict],
            "answer_summary": str,
            "confidence": Confidence,
        }
    ],
}
```

### Artifact Evidence

```python
"artifact_evidence": {
    "generated_sql": str,  # Joined from all tasks
    "validated_sql": str,
    "parallel_tasks": [task_id, ...],
}
```

---

## `inline_data_worker()`

**File:** `app/graph/standalone_visualization.py` lines 44–219

### Signature

```python
def inline_data_worker(task_state: TaskState) -> dict[str, Any]
```

### Input (`TaskState`)

```python
{
    "query": str,          # User's visualization request
    "raw_data": list[dict],  # [{Category: str, Value: float}, ...]
}
```

### Key Constraint

> **This worker NEVER touches the database.** It:
> - Does NOT call `validate_sql()`
> - Does NOT execute any SQL
> - Accepts raw data directly from user input

### Processing Pipeline

1. **Validate input** — checks `raw_data` is non-empty
2. **Generate code** — LLM generates Python visualization via `prompt_manager.visualization_messages()`
3. **Upload CSV** — writes raw data to E2B sandbox as `/home/user/query_data.csv`
4. **Execute** — runs Python code in E2B sandbox via `sbx.run_code()`
5. **Extract image** — parses `execution.results` for PNG/JPEG base64

### Returns

```python
{
    # Visualization result
    "visualization": {
        "success": bool,
        "image_data": str,  # base64
        "image_format": "png" | "jpeg",
        "code_executed": str,
        "execution_time_ms": float,
        "terminal": bool,
        "recommended_next_action": str,
        # On failure:
        "error": str,
    },
    "status": "success" | "failed" | "skipped",

    # WorkerArtifact fields
    "artifact_type": "chart",
    "artifact_status": "success" | "failed",
    "artifact_payload": {
        "image_data": str,
        "image_format": str,
        "chart_type": str,
        "normalized_rows": int,
    },
    "artifact_evidence": {
        "source": "inline_data",
        "normalized_rows": int,
    },
    "artifact_terminal": True,  # Always terminal on success
    "artifact_recommended_action": "finalize",
}
```

---

## `retrieve_rag_answer()`

**File:** `app/tools/retrieve_rag_answer.py`

### Signature

```python
def retrieve_rag_answer(query: str, top_k: int = 4) -> dict[str, Any]
```

### Input

| Field | Type | Default |
|-------|------|---------|
| `query` | `str` | — |
| `top_k` | `int` | 4 |

### Current Status

> **Stub implementation.** Returns empty context. Full RAG not yet integrated.

### Returns

```python
{
    "query": str,
    "top_k": int,
    "answer": "Không có thông tin",
    "sources": list,
    "status": "stub",

    # WorkerArtifact fields
    "artifact_type": "rag_context",
    "artifact_status": "failed",  # No context available
    "artifact_payload": {
        "chunks": [],
        "chunk_count": 0,
        "answer": "Không có thông tin",
    },
    "artifact_evidence": {
        "source": "rag_index",
        "query": str,
    },
    "artifact_terminal": False,
    "artifact_recommended_action": "clarify",
}
```

---

## `generate_report` (report_subgraph)

**File:** `app/graph/report_subgraph.py`

### Graph Structure

```
START → report_planner → report_executor → report_writer → report_critic
                                                              │
                               ┌──────────────────────────────┘
                               ▼
                         report_finalize → END
```

### Nodes

| Node | Model | Purpose |
|------|-------|---------|
| `report_planner` | `model_report_planner` | Decompose into sections |
| `report_executor` | `model_sql_worker` | Parallel SQL execution per section |
| `report_writer` | `model_report_writer` | Generate markdown |
| `report_critic` | `model_report_critic` | Evaluate groundedness |
| `report_finalize` | — | Construct `AnswerPayload` |

### Returns (from `report_finalize_node`)

```python
{
    "final_answer": str,           # Markdown report
    "final_payload": AnswerPayload,
    "report_final": str,
    "report_status": "done",
    "intent": "sql",
    "confidence": "high" | "medium",
    "response_mode": "report",
    "tool_history": list[dict],
    "step_count": int,
}
```

### Report Sections (per section result)

```python
{
    "section_id": str,
    "title": str,
    "analysis_query": str,
    "sql_result": dict,
    "result_ref": dict | None,
    "visualization": dict | None,
    "status": "done" | "failed",
    "error": str | None,
    "generated_sql": str,
    "validated_sql": str,
}
```

---

## WorkerArtifact: Standard Contract

All workers MUST return these fields for `artifact_evaluator` consumption:

| Field | Type | Required |
|-------|------|----------|
| `artifact_type` | `Literal` | Yes |
| `artifact_status` | `Literal` | Yes |
| `artifact_payload` | `dict` | Yes |
| `artifact_evidence` | `dict` | Yes |
| `artifact_terminal` | `bool` | Yes |
| `artifact_recommended_action` | `Literal` | Yes |

### `artifact_evaluator` Logic (`app/graph/nodes.py` lines 918+)

1. **Coverage check** — ensures `required_capabilities` from `TaskProfile` are met
2. **Retry check** — detects failed artifacts with `retry_sql`/`ask_rag`
3. **Terminal check** — if any artifact is terminal, can finalize
4. **Confidence check** — low confidence → `wait_for_user`
5. **Max steps** — exceeds limit → force finalize

### Routing Decision

```python
{
    "decision": "finalize" | "continue" | "retry" | "wait_for_user",
    "reason": str,
    "retry_tool": str | None,  # "ask_sql_analyst" | "retrieve_rag_answer"
}
```
