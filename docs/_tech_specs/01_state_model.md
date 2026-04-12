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
    data_source: Literal["inline_data", "uploaded_table", "database", "mixed", "none"]
    required_capabilities: list[Literal["sql", "visualization", "report"]]
    followup_mode: Literal["fresh_query", "followup", "refine_previous_result"]
    confidence: Literal["high", "medium", "low"]
    reasoning: str
```

### `WorkerArtifact` structure

```python
class WorkerArtifact(TypedDict, total=False):
    artifact_type: Literal["sql_result", "chart", "report_draft"]
    status: Literal["success", "failed", "partial"]
    payload: dict[str, Any]
    evidence: dict[str, Any]
    terminal: bool
    recommended_next_action: Literal["finalize", "visualize", "retry_sql", "clarify", "none"]
```

---

## Context Fields

| Field | Type | Purpose |
|-------|------|---------|
| `schema_context` | `str` | Schema overview string |
| `session_context` | `str` | Injected conversation memory |
| `continuity_context` | `dict` | Follow-up detection result |
| `table_contexts` | `dict[str, str]` | Business context per table |
| `uploaded_file_data` | `list[dict]` | Parsed CSV/data file contents |

---

## Execution Fields

| Field | Type | Purpose |
|-------|------|---------|
| `generated_sql` | `str` | LLM-generated SQL |
| `validated_sql` | `str` | Sanitized + validated SQL |
| `sql_result` | `dict` | Execution result `{rows, row_count, columns}` |
| `analysis_result` | `dict` | LLM analysis of results |
| `visualization` | `dict` | Chart spec/image data (primary/last chart) |
| `visualizations` | `list[dict]` | All successful chart results from leader loop (multi-chart support) |
| `execution_mode` | `str` | `"linear"`, `"parallel"`, or `"leader_loop"` |
| `result_ref` | `dict` | Lightweight metadata: `{result_id, row_count, columns, sample, stats}` |
| `tool_history` | `list[dict]` | Observability log of subgraph tool calls; leader entries may include a bounded `plan` object |

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
    visualizations: list[dict]    # All successful chart results (multi-chart support)
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
| `report_original_request` | `str` | Preserved raw report request for downstream planning/writing |
| `report_user_objective` | `str` | Grounded analytical objective extracted from the raw request |
| `report_user_questions` | `list[ReportQuestion]` | Explicit questions that must be answered or explained |
| `report_user_hypotheses` | `list[ReportHypothesis]` | Explicit hypotheses extracted from the request |
| `report_constraints` | `ReportConstraint` | Output language, viz preference, section/style constraints |
| `report_followup_context` | `ReportFollowupContext` | Follow-up mode + summarized session context for report planning |
| `dataset_profile` | `DatasetProfile` | Dataset affordances, selected tables, and profiling risks derived before planning |
| `report_planning_brief` | `ReportPlanningBrief` | Structured brief passed into the planner |
| `report_question_coverage` | `ReportCoverageSummary` | Coverage proof for must-answer questions |
| `report_unresolved_items` | `list[ReportUnresolvedItem]` | Required asks the planner could not cover directly |
| `report_plan` | `ReportPlan` | Planned sections (includes `domain_context`, coverage summary, unresolved items) |
| `report_sections` | `list[ReportSection]` | Executed sections with `plan`, `evidence_packets`, `claims`, visualization, and narrative |
| `report_draft` | `str` | Assembler output |
| `report_final` | `str` | Finalized report |
| `critic_feedback` | `str` | Validator/critic feedback kept for compatibility |
| `critic_iteration` | `int` | Number of assembler revision attempts |
| `report_confidence_rationale` | `str` | Human-readable explanation for the final report confidence |
| `report_status` | `ReportStatus` | `"planning"` → `"executing"` → `"insighting"` → `"writing"` → `"critiquing"` → `"done"` |
| `report_sample_data` | `dict[str, Any]` | Output of `profiler_sampler_node`: 100 random rows + column stats per table |
| `report_data_profile` | `dict[str, Any]` | Legacy compatibility alias to `dataset_profile` during the rebuild |

### `DatasetProfile` structure

```python
class DatasetProfile(TypedDict, total=False):
    candidate_tables: list[str]
    selected_tables: list[str]
    table_profiles: list[dict[str, Any]]
    join_hints: list[dict[str, Any]]
    profiling_risks: list[str]
    dataset_summary: str
    key_metrics: list[str]
    key_dimensions: list[str]
    analytical_angles: list[str]
```

### `ReportPlanningBrief` additions

```python
class ReportPlanningBrief(TypedDict, total=False):
    original_request: str
    objective: str
    user_questions: list[ReportQuestion]
    user_hypotheses: list[ReportHypothesis]
    constraints: ReportConstraint
    followup_context: ReportFollowupContext
    answerable_question_ids: list[str]
    risky_question_ids: list[str]
    unanswerable_question_ids: list[str]
    hypothesis_assessment: list[dict[str, Any]]
    domain_context: str
    planning_risks: list[str]
    suggested_analytical_directions: list[str]
```

### `ReportSection` structure

```python
class ReportSection(TypedDict, total=False):
    section_id: str
    title: str
    plan: SectionPlan
    business_question: str
    analysis_query: str
    analysis_type: Literal["descriptive", "comparative", "trend", "distribution", "composition", "correlation", "cohort", "funnel"]
    target_metrics: list[str]
    target_dimensions: list[str]
    expected_grain: str
    confidence_notes: str
    requires_visualization: bool  # planner decides; False = skip sandbox chart
    inclusion_reason: str
    addresses_question_ids: list[str]
    tests_hypothesis_ids: list[str]
    must_include: bool
    sql_result: dict[str, Any]
    evidence_requests: list[EvidenceRequest]
    evidence_packets: list[EvidencePacket]
    claims: list[ClaimPacket]
    computed_stats: dict[str, Any] | None
    visualization: dict[str, Any] | None
    chart_manifest: dict[str, Any] | None
    narrative: str
    insight_markdown: str
    insight_citations: list[dict[str, Any]]
    limitations: list[str]
    validation: dict[str, Any]
    semantic_warnings: list[str]
    semantic_status: Literal["ok", "warning", "failed"]
    section_confidence: Literal["low", "medium", "high"]
    analysis_status: Literal["pending", "done", "failed"]
    status: Literal["pending", "done", "failed"]
    error: str | None
    generated_sql: str
    validated_sql: str
    section_order: int  # Original planner position for sorting after fan-in
```

### `EvidenceRequest`, `EvidencePacket`, and `ClaimPacket`

```python
class EvidenceRequest(TypedDict, total=False):
    request_id: str
    section_id: str
    purpose: str
    request_type: Literal["metric", "breakdown", "trend", "comparison", "anomaly"]
    metric_specs: list[dict[str, Any]]
    dimension_specs: list[dict[str, Any]]
    filter_specs: list[dict[str, Any]]
    expected_grain: str
    analysis_query: str


class EvidencePacket(TypedDict, total=False):
    packet_id: str
    section_id: str
    request_id: str
    sql: str
    validated_sql: str
    row_count: int
    result_ref: dict[str, Any] | None
    grouped_rows: list[dict[str, Any]]
    series_rows: list[dict[str, Any]]
    comparisons: list[dict[str, Any]]
    metrics: dict[str, Any]
    denominators: dict[str, Any]
    grain: str
    quality_warnings: list[str]
    evidence_paths: list[str]
    underlying_observation_count: int | None


class ClaimPacket(TypedDict, total=False):
    claim_id: str
    section_id: str
    claim_type: Literal["observation", "comparison", "trend", "hypothesis"]
    text: str
    evidence_refs: list[str]
    caveats: list[str]
    confidence: Literal["low", "medium", "high"]
    recommendation_ready: bool
```

### `ReportPlan` structure

```python
class ReportPlan(TypedDict, total=False):
    title: str
    executive_summary_instruction: str
    sections: list[ReportSection]
    conclusion_instruction: str
    domain_context: str  # profiler-derived domain summary passed to writer
    coverage_summary: ReportCoverageSummary
    unresolved_items: list[ReportUnresolvedItem]
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
| `intent` | `Intent` | `"sql"`, `"mixed"`, `"unknown"` |
| `intent_reason` | `str` | Why intent was chosen |
| `artifact_evaluation` | `dict` | Decision from `artifact_evaluator` |
| `clarification_question` | `str` | Human question when `wait_for_user` |

### Leader tool-history plan shape

For leader-originated tool calls, `tool_history` entries may include:

```python
{
    "tool": str,
    "status": str,
    "reason": str,
    "plan": {
        "goal": str,
        "dimensions_to_check": list[str],
        "why_this_tool": str,
        "success_criteria": str,
    },
    "source": "leader_agent",
}
```

`plan` is optional and used as a bounded micro-plan for multi-step reasoning, especially diagnostic and comparative queries.

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
