# AgentState: Complete State Model

> Source: `app/graph/state.py`

## Overview

`AgentState` is a `TypedDict` (total=False) shared across all nodes in the LangGraph. Fields are grouped by lifecycle phase.

---

## Input Fields

Only present at graph entry via `GraphInputState`.

| Field | Type | Purpose |
|-------|------|---------|
| `user_query` | `str` | Raw user question |
| `target_db_path` | `str` | Optional: path to SQLite eval DB (Spider), or None for PostgreSQL |
| `user_semantic_context` | `str` | User-provided domain context |
| `uploaded_files` | `list[str]` | File paths from file upload |
| `uploaded_file_data` | `list[dict]` | Parsed file contents |
| `thread_id` | `str` | Session scoping ID (optional at input) |

---

## Grounding (v4) — set by `task_grounder`

These fields are set once at graph entry and flow down to all downstream nodes.

| Field | Type | Purpose |
|-------|------|---------|
| `task_profile` | `TaskProfile` | Structured classification from grounder |
| `artifacts` | `Annotated[list[WorkerArtifact], operator.add]` | Fan-in from all workers |
| `xml_database_context` | `str` | Full `<database_context>` XML block for SQL agents |

### `TaskProfile` structure

```python
class TaskProfile(TypedDict, total=False):
    task_mode: Literal["simple", "mixed", "ambiguous"]
    data_source: Literal["inline_data", "uploaded_table", "database", "knowledge", "mixed"]
    required_capabilities: list[Literal["sql", "rag", "visualization", "report"]]
    followup_mode: Literal["fresh_query", "followup", "refine_previous_result"]
    confidence: Literal["high", "medium", "low"]
    reasoning: str
```

### `WorkerArtifact` structure

```python
class WorkerArtifact(TypedDict, total=False):
    artifact_type: Literal["sql_result", "rag_context", "chart", "report_draft"]
    status: Literal["success", "failed", "partial"]
    payload: dict[str, Any]
    evidence: dict[str, Any]
    terminal: bool
    recommended_next_action: Literal["finalize", "visualize", "retry_sql", "ask_rag", "clarify", "none"]
```

---

## Context Fields

| Field | Type | Purpose |
|-------|------|---------|
| `schema_context` | `str` | Schema overview string |
| `session_context` | `str` | Injected conversation memory |
| `continuity_context` | `dict` | Follow-up detection result |
| `table_contexts` | `dict[str, str]` | Business context per table |
| `retrieved_context` | `list[dict]` | RAG retrieval results |
| `uploaded_file_data` | `list[dict]` | Parsed CSV/data file contents |

---

## Execution Fields

| Field | Type | Purpose |
|-------|------|---------|
| `generated_sql` | `str` | LLM-generated SQL |
| `validated_sql` | `str` | Sanitized + validated SQL |
| `sql_result` | `dict` | Execution result `{rows, row_count, columns}` |
| `analysis_result` | `dict` | LLM analysis of results |
| `visualization` | `dict` | Chart spec/image data |
| `execution_mode` | `str` | `"linear"`, `"parallel"`, or `"leader_loop"` |
| `result_ref` | `dict` | Lightweight metadata: `{result_id, row_count, columns, sample, stats}` |

---

## Output Fields

| Field | Type | Purpose |
|-------|------|---------|
| `final_answer` | `str` | Natural language answer |
| `final_payload` | `AnswerPayload` | Structured response with metadata |
| `response_mode` | `ResponseMode` | `"answer"` or `"report"` |

### `AnswerPayload` fields

```python
class AnswerPayload(TypedDict, total=False):
    answer: str
    report_markdown: str | None
    evidence: list[str]
    confidence: Confidence
    confidence_rationale: str
    used_tools: list[str]
    generated_sql: str
    error_categories: list[str]
    step_count: int
    total_token_usage: int
    total_cost_usd: float
    sql_rows: list[dict]
    sql_row_count: int
    visualization: dict | None
    result_metadata: dict | None
```

---

## Memory Fields

| Field | Type | Purpose |
|-------|------|---------|
| `thread_id` | `str` | Thread identifier |
| `conversation_turn` | `int` | Current turn number |
| `last_action` | `dict` | Previous SQL, params, result summary |
| `skipped_tables` | `list[str]` | Tables skipped due to caching |

---

## Report Fields

| Field | Type | Purpose |
|-------|------|---------|
| `report_request` | `str` | User's report request |
| `report_plan` | `ReportPlan` | Planned sections (includes `domain_context` from profiler) |
| `report_sections` | `list[ReportSection]` | Executed sections |
| `report_draft` | `str` | Writer output |
| `report_final` | `str` | Finalized report |
| `critic_feedback` | `str` | Critic evaluation |
| `critic_iteration` | `int` | Number of revisions |
| `report_confidence_rationale` | `str` | Human-readable explanation for the final report confidence |
| `report_status` | `ReportStatus` | `"planning"` → `"executing"` → `"insighting"` → `"writing"` → `"critiquing"` → `"done"` |
| `report_sample_data` | `dict[str, Any]` | Output of `profiler_sampler_node`: 100 random rows + column stats per table |
| `report_data_profile` | `dict[str, Any]` | Output of `profiler_analyzer_node`: domain summary, key metrics, suggested sections |

### `ReportSection` structure

```python
class ReportSection(TypedDict, total=False):
    section_id: str
    title: str
    analysis_query: str
    analysis_type: Literal["descriptive", "comparative", "trend", "distribution", "composition", "correlation", "cohort", "funnel"]
    target_metrics: list[str]
    target_dimensions: list[str]
    expected_grain: str
    confidence_notes: str
    requires_visualization: bool  # planner decides; False = skip sandbox chart
    sql_result: dict[str, Any]
    computed_stats: dict[str, Any] | None
    chart_image: dict[str, Any] | None
    chart_manifest: dict[str, Any] | None
    insight_markdown: str
    insight_citations: list[dict[str, Any]]
    limitations: list[str]
    semantic_warnings: list[str]
    semantic_status: Literal["ok", "warning", "failed"]
    section_confidence: Literal["low", "medium", "high"]
    analysis_status: Literal["pending", "done", "failed"]
    status: Literal["pending", "done", "failed"]
    error: str | None
    generated_sql: str
    validated_sql: str
    section_order: int  # Original planner position for sorting after fan-in
    critic_decision: str  # Feedback from report_critic node
```

### `ReportPlan` structure

```python
class ReportPlan(TypedDict, total=False):
    title: str
    executive_summary_instruction: str
    sections: list[ReportSection]
    conclusion_instruction: str
    domain_context: str  # profiler-derived domain summary passed to writer
```

---

## Observability Fields

| Field | Type | Purpose |
|-------|------|---------|
| `run_id` | `str` | Unique run identifier |
| `tool_history` | `Annotated[list[dict], operator.add]` | Fan-in of all tool calls |
| `errors` | `Annotated[list[dict], operator.add]` | Fan-in of all errors |
| `step_count` | `int` | Node execution counter |
| `confidence` | `Confidence` | `"high"`, `"medium"`, or `"low"` |
| `intent` | `Intent` | `"sql"`, `"rag"`, `"mixed"`, `"unknown"` |
| `intent_reason` | `str` | Why intent was chosen |
| `artifact_evaluation` | `dict` | Decision from `artifact_evaluator` |
| `clarification_question` | `str` | Human question when `wait_for_user` |

---

## Annotated Fields (Merge Semantics)

Three fields use `Annotated[..., operator.add]`, meaning each node **appends** rather than overwrites:

```python
tool_history: Annotated[list[dict[str, Any]], operator.add]
errors: Annotated[list[dict[str, Any]], operator.add]
artifacts: Annotated[list[WorkerArtifact], operator.add]
task_results: Annotated[list[TaskState], operator.add]  # From parallel workers
_report_sections_raw: Annotated[list[ReportSection], operator.add]  # Fan-in reducer for Send() pipeline
```

All other fields are **last-write-wins** (node output replaces prior value).

---

## State Transitions

```
START
  │
  ▼
process_uploaded_files  ──►  inject_session_context
                                      │
                                      ▼
                               task_grounder  ──►  leader_agent
                                      │                  │
                                      │    (loop 1-5)    │
                                      │         │        │
                                      │    tool calls    │
                                      │         │        │
                                      ▼         ▼        ▼
                              artifact_evaluator  ◄──────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              ▼                       ▼                       ▼
       leader_agent              clarify_question       capture_action_node
       (retry/continue)           (interrupt)              │
              │                                               ▼
              │                                    compact_and_save_memory
              │                                           │
              └───────────────────────────────────────────┘
                                          │
                                          ▼
                                          END
```

---

## GraphOutputState: What Leaks to API

Only these fields are exposed in the graph output schema:

```python
class GraphOutputState(TypedDict, total=False):
    final_answer: str
    final_payload: AnswerPayload
    intent: Intent
    intent_reason: str
    errors: list[dict]          # Flattened (not Annotated)
    step_count: int
    run_id: str
    context_type: ContextType
    needs_semantic_context: bool
    task_results: list[TaskState]
    tool_history: list[dict]
    response_mode: ResponseMode
    artifact_evaluation: dict
```

> Note: `artifacts` (the `WorkerArtifact` list) is **not** in `GraphOutputState`. It is tracked internally via the tracer.
