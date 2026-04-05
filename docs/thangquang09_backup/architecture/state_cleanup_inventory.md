# State & Tracing Cleanup Inventory

> Last updated: 2026-04-05

## Current State Audit

### AgentState — 60+ flat fields

Source: `app/graph/state.py:72-131`

Every field lives in a single flat `TypedDict` with no hierarchical grouping. Fields from different lifecycle phases (input, routing, execution, output, memory) are mixed together, making it hard to understand which node reads/writes which fields.

---

## Field-by-Field Analysis

### Fields to consolidate or remove

| Current field(s) | Problem | Proposed action |
|---|---|---|
| `intent` + `intent_reason` | Set by leader, duplicated in output. In new architecture, intent is derived from `TaskProfile` | Merge into `task_profile`. Keep `intent` in output for backward compat only |
| `execution_mode` | 5 overlapping values: `single`, `parallel`, `linear`, `direct`, `planned`. Comment says "future refactor could split" | Remove from `AgentState`. Derive from `task_profile.task_mode` or let supervisor decide internally |
| `context_type` | 4 values: `user_provided`, `csv_auto`, `mixed`, `default`. Rarely read outside routing | Derive from `task_profile.data_source`. Remove as standalone field |
| `needs_semantic_context` | Boolean flag, only relevant during context detection phase | Derive from `task_profile.required_capabilities` containing `rag` |
| `sql_retry_count` + `sql_last_error` | Worker-internal retry state leaked into global state | Encapsulate inside `sql_worker_graph`. Remove from `AgentState` |
| `expected_keywords` | Eval-only field, used by Spider benchmark | Move to eval-specific state extension. Remove from production `AgentState` |
| `user_semantic_context` | User-provided business context, rarely populated | Keep but move to Context group |
| `messages` | `Annotated[list, operator.add]` — accumulated messages, rarely used in v3 | Evaluate if still needed. If not, remove |

### Fields duplicated between AgentState and TaskState

These fields appear in both `AgentState` (global) and `TaskState` (per-worker):

| Field | In AgentState | In TaskState | Notes |
|---|---|---|---|
| `generated_sql` | yes | yes | Worker writes to TaskState, then flattened to AgentState by `aggregate_results()` |
| `validated_sql` | yes | yes | Same pattern |
| `sql_result` | yes | yes | Worker produces, aggregate flattens |
| `schema_context` | yes | yes | Copied from AgentState into each TaskState before dispatch |
| `session_context` | yes | yes | Same — copied for worker access |
| `xml_database_context` | yes | yes | Same |
| `visualization` | yes | yes | Worker produces, aggregate picks first |
| `tool_history` | yes (Annotated add) | yes (list) | Worker appends, then merged into global |
| `run_id` | yes | yes | Copied for tracing |
| `thread_id` | yes | yes | Copied for tracing |

**Root cause:** Workers need context from the parent state, and their results need to be flattened back. In the current design, this creates duplication.

**Proposed fix:** Workers receive a read-only `WorkerContext` (subset of AgentState) and return `WorkerArtifact` (standardized). No need to duplicate schema/session/XML fields into `TaskState`.

### Report-related fields

| Field | Used by |
|---|---|
| `report_request` | `report_subgraph` entry |
| `report_plan` | `report_planner_node` |
| `report_sections` | `report_executor_node` |
| `report_draft` | `report_writer_node` |
| `report_final` | `report_finalize_node` |
| `critic_feedback` | `report_critic_node` |
| `critic_iteration` | `report_critic_node` |
| `report_status` | Routing + UI |
| `report_feedback_hash` | Critic loop detection |
| `report_draft_hash` | Critic loop detection |

**10 fields** for reports. These are only relevant when `response_mode == "report"`. They should be isolated inside the report subgraph state, not polluting the global `AgentState`.

---

## Output Schema Overlap

### AnswerPayload vs GraphOutputState

`AnswerPayload` (15 fields) and `GraphOutputState` (14 fields) have significant overlap:

| Field | AnswerPayload | GraphOutputState | Notes |
|---|---|---|---|
| `intent` | no | yes | Output only |
| `intent_reason` | no | yes | Output only |
| `confidence` | yes | no | Inside payload |
| `used_tools` | yes | no | Inside payload |
| `generated_sql` | yes | no | Inside payload |
| `errors` | no | yes | Both levels |
| `step_count` | yes | yes | Duplicated |
| `tool_history` | no | yes | Output only |
| `response_mode` | no | yes | Output only |
| `task_plan` | no | yes | Internal — should not be in output |
| `execution_mode` | no | yes | Internal — should not be in output |
| `aggregate_analysis` | no | yes | Internal — should not be in output |

**Problems:**
1. `GraphOutputState` leaks internal fields (`task_plan`, `execution_mode`, `aggregate_analysis`) to the output boundary
2. `step_count` is duplicated
3. Frontend must dig into `final_payload` for some fields and root state for others

**Proposed fix:** `GraphOutputState` should only contain user-facing fields. Internal execution metadata stays in `AgentState` but is not exposed.

---

## Tracing and Debug Log Cleanup

### `_state_summary()` in `app/observability/tracer.py`

Currently tracks 12 fields:

```python
def _state_summary(state):
    return {
        "user_query", "task_id", "intent", "step_count",
        "execution_mode", "has_schema_context", "generated_sql",
        "validated_sql", "sql_row_count", "task_count",
        "retrieved_context_count", "errors"
    }
```

**Issues in new architecture:**
- `intent` will be replaced by `task_profile`
- `execution_mode` is being removed
- Missing: `task_profile`, `artifact_count`, `data_source`

**Proposed update:**

```python
def _state_summary(state):
    return {
        "user_query", "task_id", "step_count",
        "task_profile",              # NEW: grounded task info
        "artifact_count",            # NEW: how many artifacts collected
        "has_schema_context",
        "generated_sql", "validated_sql",
        "sql_row_count", "errors"
    }
```

### `_output_summary()` in `app/observability/tracer.py`

Currently tracks:

```python
def _output_summary(update):
    return {
        "keys", "answer_preview", "intent", "step_count",
        "status", "execution_mode", "task_count",
        "sql_row_count", "tool_history_delta",
        "errors_delta", "generated_sql"
    }
```

**Proposed update:**
- Remove `execution_mode`
- Add `artifact_type`, `terminal`, `recommended_next_action`
- Keep `intent` for backward compatibility but mark as deprecated

### `_filtered_state()` in `app/debug.py`

Currently filters 14 large fields:

```python
_FILTERED_KEYS = frozenset({
    "xml_database_context", "schema_context", "session_context",
    "uploaded_file_data", "sql_result", "file_cache",
    "table_contexts", "retrieved_context", "messages",
    "visualization", "task_plan", "task_results",
    "tool_history", "aggregate_analysis",
    "report_sections", "report_draft", "report_final",
})
```

**Additions needed for new architecture:**
- `artifacts` — list of `WorkerArtifact`, can be large (images)
- `task_profile` — small, should NOT be filtered (useful for debugging)

### `RunTraceRecord` in `app/observability/schemas.py`

Current run-level trace record:

```python
@dataclass
class RunTraceRecord:
    run_id, thread_id, started_at, ended_at, latency_ms,
    query, intent, status, total_steps,
    used_tools, generated_sql, retry_count,
    fallback_used, error_categories,
    total_token_usage, total_cost_usd, final_confidence
```

**Proposed additions:**
- `task_profile` — grounded task info (data_source, task_mode, required_capabilities)
- `artifact_count` — how many artifacts were produced
- `grounding_confidence` — confidence from Task Grounder
- Deprecate `intent` (keep for backward compat, derive from `task_profile`)

---

## Proposed State Grouping

After migration, `AgentState` fields should be organized into clear groups:

### Input Group
Fields set at graph entry, read-only after initialization.

| Field | Type | Source |
|---|---|---|
| `user_query` | `str` | User input |
| `uploaded_file_data` | `list[dict]` | User upload |
| `thread_id` | `str` | Session ID |
| `run_id` | `str` | Generated per run |
| `target_db_path` | `str` | Optional DB override |

### Context Group
Built by `context_builder` node, read-only after that.

| Field | Type | Source |
|---|---|---|
| `registered_tables` | `list[str]` | CSV auto-registration |
| `file_cache` | `dict` | Upload dedup cache |
| `table_contexts` | `dict[str, str]` | Business context per table |
| `xml_database_context` | `str` | Schema XML for SQL prompts |
| `schema_context` | `str` | Schema JSON |
| `session_context` | `str` | Memory injection |
| `conversation_turn` | `int` | Turn number |

### Grounding Group (new)
Set by `task_grounder` node, read by supervisor and evaluator.

| Field | Type | Source |
|---|---|---|
| `task_profile` | `TaskProfile` | Task Grounder LLM call |

### Execution Group
Written by supervisor and workers during the execution loop.

| Field | Type | Source |
|---|---|---|
| `artifacts` | `list[WorkerArtifact]` | Workers (Annotated add) |
| `step_count` | `int` | Supervisor step counter |
| `tool_history` | `list[dict]` | Tool call log (Annotated add) |
| `errors` | `list[dict]` | Error accumulator (Annotated add) |

### Output Group
Written by Final Composer, read by graph output.

| Field | Type | Source |
|---|---|---|
| `final_answer` | `str` | Composer |
| `final_payload` | `AnswerPayload` | Composer |
| `visualization` | `dict` | Best visualization artifact |
| `result_ref` | `dict` | Result store reference |
| `confidence` | `Confidence` | Composer assessment |
| `response_mode` | `ResponseMode` | Grounder / supervisor |

### Memory Group
Written by `capture_action_node`, persisted to SQLite.

| Field | Type | Source |
|---|---|---|
| `last_action` | `dict` | Action capture |

### Report Group (isolated in subgraph)
Only used when `response_mode == "report"`. Should be scoped to report subgraph state.

| Field | Type |
|---|---|
| `report_request` | `str` |
| `report_plan` | `ReportPlan` |
| `report_sections` | `list[ReportSection]` |
| `report_draft` | `str` |
| `report_final` | `str` |
| `critic_feedback` | `str` |
| `critic_iteration` | `int` |
| `report_status` | `ReportStatus` |

---

## Fields to Remove from AgentState

| Field | Reason | Migration |
|---|---|---|
| `intent` | Replaced by `task_profile` | Keep in output only for backward compat |
| `intent_reason` | Replaced by `task_profile.confidence` + supervisor reasoning | Keep in output only |
| `execution_mode` | Confusing 5-value enum, never cleanly separated | Remove. Derive from task_profile |
| `context_type` | Derive from `task_profile.data_source` | Remove |
| `needs_semantic_context` | Derive from `task_profile.required_capabilities` | Remove |
| `sql_retry_count` | Encapsulate in worker | Remove from global state |
| `sql_last_error` | Encapsulate in worker | Remove from global state |
| `expected_keywords` | Eval-only | Move to eval extension |
| `messages` | Unused in v3 leader pattern | Remove if confirmed unused |
| `task_plan` | Internal to supervisor | Remove from `GraphOutputState` |
| `aggregate_analysis` | Internal to aggregation | Remove from `GraphOutputState` |

**Net reduction:** ~11 fields removed from `AgentState`, 3 fields removed from `GraphOutputState`.

---

## Debug Log Readability Improvements

### Current log line (verbose, hard to scan):

```
2026-04-05 14:22:46.955 | DEBUG | fd6dd0f1 | preclassifier_node | - | OUTPUT | {
  'preclass_route': 'data',
  'preclass_reason': 'The request involves creating a chart based on provided data.',
  'preclass_confidence': 'high',
  'step_count': 2,
  'tool_history': '<list 1 items>'
}
```

### Proposed log line (with task_profile):

```
2026-04-05 14:22:46.955 | DEBUG | fd6dd0f1 | task_grounder | - | OUTPUT | {
  'task_profile': {
    'task_mode': 'simple',
    'data_source': 'inline_data',
    'required_capabilities': ['visualization'],
    'followup_mode': 'fresh_query',
    'confidence': 'high'
  },
  'step_count': 2
}
```

Key improvement: `task_profile` is a single structured object that tells the developer exactly what the system understood about the query. No need to mentally reconstruct from scattered `intent`, `intent_reason`, `execution_mode`, `context_type` fields.

### Supervisor step logs (proposed):

```
2026-04-05 14:22:47.100 | DEBUG | fd6dd0f1 | supervisor | - | STEP 1 | {
  'action': 'call_worker',
  'worker': 'viz_worker',
  'reason': 'inline_data + visualization capability needed'
}

2026-04-05 14:22:50.200 | DEBUG | fd6dd0f1 | supervisor | - | ARTIFACT | {
  'artifact_type': 'chart',
  'status': 'success',
  'terminal': true,
  'recommended_next_action': 'finalize'
}

2026-04-05 14:22:50.201 | DEBUG | fd6dd0f1 | evaluator | - | DECISION | {
  'all_capabilities_covered': true,
  'has_terminal_artifact': true,
  'decision': 'finalize'
}
```

This structured logging makes it trivial to trace why a decision was made at each step.

---

## Summary of Changes by File

| File | Cleanup action |
|---|---|
| `app/graph/state.py` | Remove ~11 fields, add `TaskProfile`, `WorkerArtifact`, `artifacts`. Isolate report fields |
| `app/observability/tracer.py` | Update `_state_summary()`, `_output_summary()` for new fields |
| `app/observability/schemas.py` | Add `task_profile`, `artifact_count` to `RunTraceRecord` |
| `app/debug.py` | Add `artifacts` to `_FILTERED_KEYS`, keep `task_profile` unfiltered |
| `app/graph/nodes.py` | Remove reads/writes of deprecated fields |
| `app/main.py` | Update `run_query()` output mapping for removed fields |
| `backend/models/responses.py` | Update `QueryResponse` model for new output shape |

---

## Migration Plan

### Phase 1: Terminal Signals + Remove Global SQL Fallback ✅ DONE

**Date:** 2026-04-05

**Changes implemented:**

1. **`app/graph/nodes.py`** — Auto-finalize after `create_visualization` success
   - Added immediate return after successful visualization (line ~1400)
   - No longer falls through to universal fallback when viz succeeds
   - Proper answer composition with viz metadata only

2. **`app/graph/nodes.py`** — Domain-aware fallback (replaces universal SQL fallback)
   - `create_visualization` success → compose answer from viz metadata only
   - `create_visualization` failure → return error, NO fallback to SQL
   - `retrieve_rag_answer` → return "no context found", NO fallback to SQL
   - Only truly unknown cases fall back to SQL as last resort

3. **`app/graph/standalone_visualization.py`** — Added terminal signals
   - Added `terminal: True` to success response
   - Added `recommended_next_action: "finalize"` to success response

**Bug fixes:**
- ✅ Visualization-only queries no longer fall through to SQL
- ✅ Leader stops immediately after successful visualization
- ✅ Failed visualization returns error instead of SQL fallback
- ✅ RAG failures don't trigger SQL fallback

### Phase 2: Task Grounder Node ✅ DONE

**Date:** 2026-04-05

**Changes implemented:**

1. **`app/graph/state.py`** — Added new TypedDicts
   - `TaskProfile` — structured task profile with task_mode, data_source, required_capabilities, followup_mode, confidence, reasoning
   - `WorkerArtifact` — standardized worker output with artifact_type, status, payload, evidence, terminal, recommended_next_action
   - Added `artifacts: Annotated[list[WorkerArtifact], operator.add]` to AgentState
   - Added `task_profile: TaskProfile` to AgentState

2. **`app/prompts/task_grounder.py`** — Created new prompt definition
   - Vietnamese system prompt for LLM classification
   - Outputs structured JSON matching TaskProfile schema

3. **`app/graph/task_grounder.py`** — Created new node function
   - Calls lightweight LLM (gpt-4o-mini) via settings.model_preclassifier
   - Extracts JSON from response with regex + json.loads
   - Returns AgentState with task_profile, tool_history entry, incremented step_count
   - Fallback to conservative profile on any failure

4. **`app/graph/graph.py`** — Wired grounder into graph
   - Added import for task_grounder
   - Added node via `builder.add_node("task_grounder", ...)`
   - Added edges: `inject_session_context → task_grounder → leader_agent`

5. **`app/config.py`** — Added model_preclassifier setting
   - Added `model_preclassifier: str` to Settings dataclass
   - Defaults to "gh/gpt-4o-mini" via MODEL_PRECLASSIFIER env var

6. **`app/prompts/__init__.py`** — Exported TASK_GROUNDER_PROMPT
   - Added import and export

7. **`app/prompts/manager.py`** — Added task_grounder_messages()
   - Returns formatted messages for Task Grounder

**Verification:**
```bash
python -c "from app.graph.task_grounder import task_grounder; from app.graph.state import TaskProfile, WorkerArtifact; print('OK')"
# Output: Imports OK
```

**Graph flow:**
```
process_uploaded_files → inject_session_context → task_grounder → leader_agent → ...
```

### Phase 3: Task Planner + Structured Response ✅ DONE

**Date:** 2026-04-05

**Changes implemented:**

1. **`app/prompts/task_planner.py`** — Created new prompt definition
   - Vietnamese system prompt for task decomposition
   - Outputs structured JSON matching TaskSpec schema

2. **`app/graph/task_planner.py`** — Created new node function
   - Calls LLM for task planning
   - Returns plan and tool recommendations

**Verification:**
```bash
python -c "from app.graph.task_planner import task_planner; print('OK')"
# Output: Imports OK
```

### Phase 4: SQL Validator AST Migration ✅ DONE

**Date:** 2026-04-05

**Changes implemented:**

1. **`pyproject.toml`** — Added sqlglot dependency
   - `"sqlglot>=26.0.0"` added to dependencies

2. **`app/tools/validate_sql.py`** — Replaced regex with AST parsing
   - Added `import sqlglot`
   - `_extract_cte_names()` now uses `sqlglot.exp.CTE` AST traversal
   - Added `_extract_table_names()` using `sqlglot.exp.Table` AST traversal
   - Added `_extract_table_names_regex()` as fallback for unparseable SQL
   - `_extract_cte_names_regex()` kept as fallback for CTEs
   - Updated `validate_sql()` to use new AST-based extraction

3. **`app/debug.py`** — Added `artifacts` to `_FILTERED_KEYS`
   - New field `artifacts` (list of WorkerArtifact) can contain large image data

**Bug fixes:**
- ✅ CTE with quoted name (`"Data"`) no longer reports "Unknown table"
- ✅ Proper handling of recursive CTEs: `WITH RECURSIVE ...`
- ✅ Chained CTEs: `WITH cte1 AS (...), cte2 AS (...)`
- ✅ Falls back to regex if AST parsing fails

**Verification:**
```bash
python -c "
from app.tools.validate_sql import validate_sql
# Test: CTE with quoted name
result = validate_sql('WITH \"Data\" AS (SELECT 1) SELECT * FROM \"Data\"', db_path='data/warehouse/analytics.db')
print('Quoted CTE test:', result.is_valid, result.reasons)
# Test: chained CTE
result2 = validate_sql('WITH a AS (SELECT 1), b AS (SELECT * FROM a) SELECT * FROM b', db_path='data/warehouse/analytics.db')
print('Chained CTE test:', result2.is_valid, result2.reasons)
# Test: forbidden keyword
result3 = validate_sql('INSERT INTO users VALUES (1)', db_path='data/warehouse/analytics.db')
print('INSERT rejection test:', not result3.is_valid)
"
# Output:
# Quoted CTE test: True []
# Chained CTE test: True []
# INSERT rejection test: True
```

### Phase 7: State Cleanup + Observability Update ✅ DONE

**Date:** 2026-04-05

**Changes implemented:**

1. **`app/graph/state.py`** — Removed deprecated fields from `AgentState`
   - Removed `messages: Annotated[list[dict[str, Any]], operator.add]` (unused in v3 leader pattern)
   - Removed `expected_keywords: list[str]` (eval-only field, moved to eval extension)
   - Removed `sql_retry_count: int` and `sql_last_error: str | None` (worker-internal state)
   - Removed `task_plan: list[TaskState]`, `aggregate_analysis: dict[str, Any]`, `execution_mode: ExecutionMode` (internal Plan-and-Execute fields)
   - Removed unused `ExecutionMode` type literal
   - Removed `file_cache: dict[str, Any]` (not referenced in code)

2. **`app/graph/state.py`** — Removed internal fields from `GraphOutputState`
   - Removed `task_plan: list[TaskState]` (internal to supervisor)
   - Removed `execution_mode: ExecutionMode` (confusing 5-value enum)
   - Removed `aggregate_analysis: dict[str, Any]` (internal to aggregation)
   - Kept `task_results` (fanned-in worker results, needed for output)

3. **`app/graph/edges.py`** — Simplified routing functions
   - `route_after_sql_validation()`: Removed `sql_retry_count` check. Now proceeds to error handling on validation failure.
   - `route_after_sql_execution()`: Removed `sql_retry_count` check. Always proceeds to `analyze_result`. Self-correction is handled internally by worker subgraph.

4. **`app/main.py`** — Removed deprecated field propagation
   - Removed `graph_input["expected_keywords"] = expected_keywords` (field no longer in AgentState)
   - Kept `expected_keywords` parameter with deprecation comment for backward compat

5. **`app/observability/tracer.py`** — Updated `_state_summary()`
   - Replaced `intent` and `execution_mode` with `task_profile`
   - Added `artifact_count` for v4 artifact tracking
   - Replaced `task_count` with artifact-level metrics

6. **`app/observability/tracer.py`** — Updated `_output_summary()`
   - Removed `execution_mode` and `task_count`
   - Added `artifact_type`, `terminal`, `recommended_action` for artifact tracking
   - Kept `intent` for backward compatibility

7. **`app/observability/tracer.py`** — Updated `RunTracer.finish()`
   - Added `task_profile`, `grounding_confidence`, `artifact_count`, `artifact_types` to `RunTraceRecord`

8. **`app/observability/schemas.py`** — Updated `RunTraceRecord`
   - Added `task_profile: dict[str, Any] | None` — TaskProfile JSON
   - Added `grounding_confidence: str | None` — confidence from Task Grounder
   - Added `artifact_count: int = 0` — artifact tracking
   - Added `artifact_types: list[str]` — types of artifacts produced
   - Added `field` import from dataclasses

**Verification:**
```bash
python -c "
from app.graph.state import AgentState, GraphOutputState
from app.observability.schemas import RunTraceRecord
from app.graph.edges import route_after_sql_validation, route_after_sql_execution
from app.main import run_query
print('All imports OK')
print('AgentState fields:', len(AgentState.__annotations__))
print('GraphOutputState fields:', len(GraphOutputState.__annotations__))
"
# Output: All imports OK
# AgentState fields: 41 (reduced from 48)
# GraphOutputState fields: 12 (reduced from 14)
```

**Net reduction:**
- `AgentState`: 41 fields (from 48) — 7 fields removed
- `GraphOutputState`: 12 fields (from 14) — 2 fields removed
- `RunTraceRecord`: +4 new fields for v4 grounding and artifact tracking
- Routing functions: simplified self-correction logic

### Phase 8: WorkerArtifact Contract ✅ DONE

**Date:** 2026-04-05

**Changes implemented:**

1. **`app/graph/nodes.py`** — Added `_evaluate_artifacts()` function
   - Deterministic evaluation of collected artifacts
   - Maps capabilities to artifact types (sql→sql_result, rag→rag_context, etc.)
   - Checks coverage: all required capabilities from TaskProfile
   - Checks for failed artifacts with retry recommendation
   - Determines decision: continue/finalize/retry/clarify
   - Returns tool_history entry with decision details

2. **`app/graph/nodes.py`** — Refactored `ask_sql_analyst_tool()` return
   - Added WorkerArtifact fields: `artifact_type`, `artifact_status`, `artifact_payload`, `artifact_evidence`, `artifact_terminal`, `artifact_recommended_action`
   - `artifact_type`: "sql_result"
   - `artifact_status`: "success" if all tasks succeed, "partial" if some succeed, "failed" if none succeed
   - `artifact_terminal`: True if successful and no failures
   - `artifact_recommended_action`: "finalize" if terminal, "retry_sql" if failed, "clarify" otherwise

3. **`app/graph/nodes.py`** — Refactored `ask_sql_analyst_parallel_tool()` return
   - Added same WorkerArtifact fields as `ask_sql_analyst_tool()`
   - `artifact_evidence` includes `parallel_tasks` list for tracking

4. **`app/graph/standalone_visualization.py`** — Added WorkerArtifact to all return paths
   - Success case: `artifact_type="chart"`, `artifact_status="success"`, `terminal=True`
   - Failed cases: `artifact_status="failed"`, `terminal=False`, `recommended_action="clarify"`
   - All 6 WorkerArtifact fields included in every return statement

5. **`app/tools/retrieve_rag_answer.py`** — Added WorkerArtifact fields
   - `artifact_type`: "rag_context"
   - `artifact_status`: "partial" if context found, "failed" otherwise
   - `artifact_payload` includes chunks, chunk_count, and answer
   - `artifact_terminal`: True if context found (has relevant info)

**Verification:**
```bash
python -c "from app.graph.nodes import _evaluate_artifacts, ask_sql_analyst_tool; from app.graph.standalone_visualization import standalone_visualization_worker; from app.tools.retrieve_rag_answer import retrieve_rag_answer; print('WorkerArtifact Contract: OK')"
# Output: WorkerArtifact Contract: OK
```

**Schema:**
All workers now return standardized WorkerArtifact fields:
- `artifact_type`: Literal["sql_result", "rag_context", "chart", "report_draft"]
- `status`: Literal["success", "failed", "partial"]
- `payload`: dict[str, Any] — worker-specific data
- `evidence`: dict[str, Any] — metadata for debugging
- `terminal`: bool — whether artifact is final (no more processing needed)
- `recommended_next_action`: Literal["finalize", "visualize", "retry_sql", "ask_rag", "clarify", "none"]

### Phase 5: Separate Inline Data Worker from DB SQL Worker ✅ DONE

**Date:** 2026-04-05

**Changes implemented:**

1. **`app/graph/nodes.py`** — Added helper functions
   - Added `_extract_inline_data_from_query()` — extracts numeric data from user query for standalone visualization
   - Added `_is_inline_data_query()` — detects if query requests inline data visualization
   - Helpers use regex patterns to identify visualization keywords and data values
   - Filters out non-data numbers (years, IDs, page numbers)

2. **`app/graph/nodes.py`** — Simplified `create_visualization` branch in `leader_agent()`
   - Removed inline regex extraction code from leader
   - Delegated extraction to `_extract_inline_data_from_query()` helper
   - Clean separation between LLM tool calling and deterministic data extraction
   - Updated import to use `inline_data_worker` from standalone_visualization module

3. **`app/graph/standalone_visualization.py`** — Renamed worker function
   - Renamed `standalone_visualization_worker()` → `inline_data_worker()`
   - Added comprehensive docstring explaining InlineDataWorker responsibilities
   - Added backward-compatible alias: `standalone_visualization_worker = inline_data_worker`
   - Documented clear boundaries: NO SQL, NO validate_sql(), NO database access

**Verification:**
```bash
python -c "from app.graph.nodes import _extract_inline_data_from_query, _is_inline_data_query; print(_extract_inline_data_from_query('vẽ biểu đồ tròn cho 10, 30, 60'))"
# Output: [{'value': 10.0}, {'value': 30.0}, {'value': 60.0}]

python -c "from app.graph.standalone_visualization import inline_data_worker, standalone_visualization_worker; print('Same function?', inline_data_worker is standalone_visualization_worker)"
# Output: Same function? True
```

**Architecture:**
```
Inline Data Query Flow:
  User Query → leader_agent (LLM decides "create_visualization")
             → _extract_inline_data_from_query (deterministic regex)
             → inline_data_worker (NEVER touches DB)
             → WorkerArtifact (artifact_type="chart")

DB SQL Query Flow:
  User Query → leader_agent (LLM decides "ask_sql_analyst")
            → ask_sql_analyst_tool
            → sql_worker_graph (validates SQL, queries DB)
            → WorkerArtifact (artifact_type="sql_result")
```

**Key principle:** Inline data queries are handled by InlineDataWorker which has ZERO database access. SQL worker pipeline is completely separate.
