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
| `state` | Parent `AgentState` | Used to extract: `target_db_path`, `schema_context`, `session_context`, `xml_database_context`, `table_contexts`, `last_action`, `thread_id`, `run_id`, and the original parent query for follow-up-safe SQL generation |
| `query` | `str` | User's SQL question |
| `allow_decomposition` | `bool` | If `True` and query is multi-part, calls `task_planner` for parallelization |

### Processing

1. If `allow_decomposition` and `_should_decompose_sql_query(query)` → calls `task_planner`
2. Parallel execution via `ThreadPoolExecutor(max_workers=4)` if multiple tasks
3. Calls `_execute_sql_analyst_task` per task (subgraph: generate → validate → execute → analyze)
4. If single task → generates natural language answer via `_generate_natural_response`
5. If multiple tasks → calls `aggregate_results` for fan-in

### Query propagation note

- Each task now carries both:
  - `query`: the focused sub-question
  - `original_user_query`: the parent user question
- SQL worker prompts use `original_user_query` as extra context so sub-queries stay anchored to the user's real intent.

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
    "artifact_path": "",
        "metadata": {
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

### Leader micro-plan note

- `ask_sql_analyst_parallel` is now the preferred execution path for leader diagnostic micro-plans.
- The leader may attach a bounded `plan` object to its own `tool_history` entry describing:
  - goal
  - dimensions to inspect
  - why the chosen tool fits
  - success criteria
- This plan is not part of the worker return contract itself; it lives at the leader orchestration layer and is mirrored into scratchpad context for subsequent leader steps.

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
/"image_url": str | None,  # URL path like "/artifacts/thread/1/chart_abc.png"/
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
    "artifact_path": "",
        "metadata": {
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

## `generate_report` (report_subgraph)

**File:** `app/graph/report_subgraph.py`

### Graph Structure

```
START → profiler_sampler → profiler_analyzer → report_planner
                                              │
                                              └─Send()→ section_pipeline (N parallel)
                                                          ↓
                                                     sections_sort
                                                          ↓
                                                     report_writer → report_critic
                                                                           │
                                              ┌────────────────────────────┘
                                              ▼
                                        report_finalize → END
```

### Nodes

| Node | Model | Purpose |
|------|-------|---------|
| `profiler_sampler` | — | Sample 100 random rows + column stats from candidate tables |
| `profiler_analyzer` | `model_report_data_profiler` | Infer domain context and suggest report sections from schema + samples |
| `report_planner` | `model_report_planner` | Build section plan (usually from profiler suggestions) |
| `section_pipeline` | `model_sql_worker` + sandbox + `model_report_writer` | Per-section SQL → grounded stats/chart → semantic validation → insight |
| `sections_sort` | — | Reassemble Send() fan-in results in planner order |
| `report_writer` | `model_report_writer` | Assemble final markdown from section evidence |
| `report_critic` | `model_report_critic` | Evaluate groundedness and revision needs |
| `report_finalize` | — | Construct `AnswerPayload`, derive confidence, and use conservative fallback if critic still rejects |

### Returns (from `report_finalize_node`)

```python
{
    "final_answer": str,           # Markdown report
    "final_payload": AnswerPayload,
    "report_final": str,
    "report_status": "done",
    "intent": "sql",
    "confidence": "high" | "medium" | "low",
    "report_confidence_rationale": str,
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
    "analysis_type": str,
    "sql_result": dict,
    "result_ref": dict | None,
    "visualization": dict | None,
    "semantic_warnings": list[str],
    "section_confidence": "low" | "medium" | "high",
    "status": "done" | "failed",
    "error": str | None,
    "generated_sql": str,
    "validated_sql": str,
}
```

### Leader visualization accumulation

- The leader loop accumulates all successful chart results in `visualization_results` (a `list[dict]`).
- On each `create_visualization` success, the chart dict is appended to this list.
- The `visualizations` field in `AgentState` and `AnswerPayload` carries the full list to the frontend.
- The singular `visualization` field retains the **last** (primary) chart for backward compatibility.
- **Auto-finalize removed**: leader no longer short-circuits on chart success. It always continues to synthesize a natural answer via `action="final"`.

### Artifact persistence (multi-chart)

- The `chart` artifact stores `items: list[dict]` containing all successful visualizations for the turn.
- `image_url`, `image_format`, etc. at the top level use the **last** chart for backward compatibility.
- Frontend renders all charts from `payload.items` with a tab selector.

---

All workers MUST return these fields for `artifact_evaluator` consumption:

| Field | Type | Required |
|-------|------|----------|
| `artifact_type` | `Literal` | Yes |
| `artifact_status` | `Literal` | Yes |
| `artifact_path` | `str` | Yes — relative path to file in `artifacts/` dir |
| `metadata` | `dict` | Yes — lightweight summary (row_count, columns, image_format, etc.) |
| `artifact_evidence` | `dict` | Yes |
| `artifact_terminal` | `bool` | Yes |
| `artifact_recommended_action` | `Literal` | Yes |

### `artifact_evaluator` Logic (`app/graph/nodes.py` lines 918+)

1. **Coverage check** — ensures `required_capabilities` from `TaskProfile` are met
2. **Retry check** — detects failed artifacts with `retry_sql`
3. **Terminal check** — if any artifact is terminal, can finalize
4. **Confidence check** — low confidence → `wait_for_user`
5. **Max steps** — exceeds limit → force finalize

### Routing Decision

```python
{
    "decision": "finalize" | "continue" | "retry" | "wait_for_user",
    "reason": str,
    "retry_tool": str | None,  # "ask_sql_analyst"
}
```
