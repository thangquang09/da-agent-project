from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict


Intent = Literal["sql", "mixed", "unknown"]
Confidence = Literal["high", "medium", "low"]
ContextType = Literal["user_provided", "csv_auto", "mixed", "default"]
ResponseMode = Literal["answer", "report"]
ReportStatus = Literal[
    "planning", "executing", "insighting", "writing", "critiquing", "done", "failed"
]
TaskType = Literal[
    "sql_query", "data_analysis", "context_lookup", "standalone_visualization"
]


# ============================================================================
# v4 Task Grounder Types
# ============================================================================


class TaskProfile(TypedDict, total=False):
    """Structured task profile produced by Task Grounder.

    Replaces the flat intent/context_type/needs_semantic_context fields
    with a single typed profile.
    """

    task_mode: Literal["simple", "mixed", "ambiguous", "chitchat"]
    data_source: Literal["inline_data", "uploaded_table", "database", "mixed", "none"]
    required_capabilities: list[Literal["sql", "visualization", "report"]]
    followup_mode: Literal["fresh_query", "followup", "refine_previous_result"]
    confidence: Literal["high", "medium", "low"]
    reasoning: str  # Why this classification was chosen


class WorkerArtifact(TypedDict, total=False):
    """Standardized output from any worker.

    Heavy data is stored on disk (via ArtifactFileStore) and referenced by
    artifact_path. The metadata dict holds lightweight summary info only
    (row_count, columns, image_format, etc.) — never raw bytes or base64.
    """

    artifact_type: Literal["sql_result", "chart", "report_draft"]
    status: Literal["success", "failed", "partial"]
    artifact_path: str  # relative path to file in artifacts/ dir
    metadata: dict[
        str, Any
    ]  # lightweight summary (row_count, columns, image_format, ...)
    evidence: dict[str, Any]
    terminal: bool
    recommended_next_action: Literal[
        "finalize", "visualize", "retry_sql", "clarify", "none"
    ]


class TaskState(TypedDict, total=False):
    """State for individual task execution in parallel workers."""

    task_id: str
    task_type: TaskType
    query: str
    original_user_query: str
    target_db_path: str
    schema_context: str
    session_context: str  # Conversation history for follow-up questions
    generated_sql: str
    validated_sql: str
    sql_result: dict[str, Any]
    analysis_result: dict[str, Any]
    status: Literal["pending", "running", "success", "failed"]
    error: str | None
    execution_time_ms: float
    requires_visualization: bool
    visualization: dict[str, Any]
    raw_data: list[
        dict[str, Any]
    ]  # For standalone visualization with user-provided data
    inherited_sql: str  # SQL inherited from previous turn for continuity
    parameter_changes: dict[str, Any]  # Parameter changes for inherited SQL
    xml_database_context: str  # XML block injected into SQL agent system prompt
    sql_retry_count: int  # Retry counter for self-correction inside worker
    sql_last_error: str | None  # Error context for self-correction
    tool_history: list[dict[str, Any]]  # Propagate tool usage from subgraph nodes
    result_ref: dict[str, Any]  # Result store reference from task execution
    run_id: str
    thread_id: str


class AnswerPayload(TypedDict, total=False):
    answer: str
    report_markdown: str | None
    report_sections: list[dict[str, Any]]
    evidence: list[str]
    confidence: Confidence
    confidence_rationale: str
    used_tools: list[str]
    generated_sql: str
    error_categories: list[str]
    step_count: int
    total_token_usage: int
    total_cost_usd: float
    unsupported_claims: list[str]
    context_type: ContextType
    sql_rows: list[dict[str, Any]]
    sql_row_count: int
    visualization: dict[str, Any] | None
    visualizations: list[dict[str, Any]]
    result_metadata: dict[str, Any] | None  # Result store metadata for frontend


class AgentState(TypedDict, total=False):
    user_query: str
    target_db_path: str
    intent: Intent
    intent_reason: str
    schema_context: str
    user_semantic_context: str
    context_type: ContextType
    needs_semantic_context: bool
    uploaded_files: list[str]
    uploaded_file_data: list[dict[str, Any]]
    registered_tables: list[str]
    generated_sql: str
    validated_sql: str
    sql_result: dict[str, Any]
    analysis_result: dict[str, Any]
    final_answer: str
    final_payload: AnswerPayload
    tool_history: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[dict[str, Any]], operator.add]
    step_count: int
    confidence: Confidence
    run_id: str
    skipped_tables: list[str]  # Tables skipped due to caching
    table_contexts: dict[
        str, str
    ]  # table_name → user-provided business context (from pair upload)
    xml_database_context: str  # Full <database_context> XML block for SQL agent
    task_results: Annotated[list[TaskState], operator.add]  # Fan-in from workers
    visualization: dict[
        str, Any
    ]  # {success, image_url, image_format, image_size_bytes, error, execution_time_ms}
    visualizations: list[dict[str, Any]]
    # Grounding Group (v4) — set by task_grounder node
    artifacts: Annotated[
        list[WorkerArtifact], operator.add
    ]  # Worker artifacts accumulated
    task_profile: TaskProfile  # Grounded task profile from grounder
    # v3 State fields
    execution_mode: str  # "linear" | "parallel" | "leader_loop" — set by task planner
    continuity_context: dict[
        str, Any
    ]  # Follow-up query context (is_continuation, inherited_action, parameter_changes)
    artifact_evaluation: dict[str, Any]  # Decision from artifact_evaluator node
    clarification_question: (
        str  # Human question from clarify decision; empty = no clarification needed
    )
    # Session memory fields
    thread_id: str  # Thread identifier for memory scoping
    session_context: str  # Injected context from conversation memory
    conversation_turn: int  # Current turn number in conversation
    last_action: dict[str, Any]  # Last completed action with SQL, parameters, etc.
    # Result store reference - lightweight metadata instead of full rows
    result_ref: dict[
        str, Any
    ]  # {result_id, row_count, columns, sample, stats, has_full_data, full_data_path}
    response_mode: ResponseMode
    report_request: str
    report_plan: "ReportPlan"
    report_sections: list["ReportSection"]
    report_draft: str
    report_final: str
    critic_feedback: str
    critic_iteration: int
    report_status: ReportStatus
    report_feedback_hash: str
    report_draft_hash: str
    report_confidence_rationale: str
    report_data_profile: dict[str, Any]  # output of report_data_profiler_node
    # Report V2: Send() fan-out fields
    report_sample_data: dict[
        str, Any
    ]  # {table: {sample_rows, column_stats}} from profiler_sampler
    _report_sections_raw: Annotated[
        list["ReportSection"], operator.add
    ]  # fan-in reducer target from Send()
    _report_sections_planned: list[
        "ReportSection"
    ]  # planner output → fan_out_sections reads this
    _current_section: "ReportSection"  # per-section Send() payload
    critic_decision: Literal["revise", "finalize"]  # explicit routing field


class GraphInputState(TypedDict, total=False):
    user_query: str
    target_db_path: str
    user_semantic_context: str
    uploaded_files: list[str]
    uploaded_file_data: list[dict[str, Any]]
    thread_id: str  # Optional: for session memory scoping
    run_id: str  # Set by run_config, needed in state for capture_action_node


class GraphOutputState(TypedDict, total=False):
    final_answer: str
    final_payload: AnswerPayload
    intent: Intent
    intent_reason: str
    errors: list[dict[str, Any]]
    step_count: int
    run_id: str
    context_type: ContextType
    needs_semantic_context: bool
    task_results: list[TaskState]
    tool_history: list[dict[str, Any]]
    response_mode: ResponseMode
    artifact_evaluation: dict[str, Any]


class ReportSection(TypedDict, total=False):
    section_id: str
    title: str
    analysis_query: str
    analysis_type: Literal[
        "descriptive",
        "comparative",
        "trend",
        "distribution",
        "composition",
        "correlation",
        "cohort",
        "funnel",
    ]
    target_metrics: list[str]
    target_dimensions: list[str]
    expected_grain: str
    confidence_notes: str
    requires_visualization: bool  # planner decides; False = skip sandbox chart
    section_order: int  # original planner order for reassembly after Send() fan-in
    sql_result: dict[str, Any]
    result_ref: dict[str, Any] | None
    raw_result_ref: dict[str, Any] | None
    visualization: dict[str, Any] | None
    sandbox_analysis: dict[str, Any] | None
    computed_stats: dict[str, Any] | None
    chart_image_url: str | None  # relative path like "{thread}/{turn}/section_{id}.png"
    chart_image_format: str | None  # "png" | "svg" etc.
    chart_html: str | None
    chart_manifest: dict[str, Any] | None
    narrative: str
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


class ReportPlan(TypedDict, total=False):
    title: str
    executive_summary_instruction: str
    sections: list[ReportSection]
    conclusion_instruction: str
    domain_context: str  # profiler-derived domain summary passed to writer
