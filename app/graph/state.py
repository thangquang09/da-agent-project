from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict


Intent = Literal["sql", "rag", "mixed", "unknown"]
Confidence = Literal["high", "medium", "low"]
ContextType = Literal["user_provided", "csv_auto", "mixed", "default"]
ResponseMode = Literal["answer", "report"]
ReportStatus = Literal["planning", "executing", "writing", "critiquing", "done", "failed"]
TaskType = Literal[
    "sql_query", "data_analysis", "context_lookup", "standalone_visualization"
]
# Router sets "direct" or "planned" (whether to invoke task_planner).
# Task planner sets "single", "parallel", or "linear" (how the plan is executed).
# Both layers are active; future refactor could split into RouterMode | PlannerMode.
ExecutionMode = Literal["single", "parallel", "linear", "direct", "planned"]


class TaskState(TypedDict, total=False):
    """State for individual task execution in parallel workers."""

    task_id: str
    task_type: TaskType
    query: str
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
    evidence: list[str]
    confidence: Confidence
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
    result_metadata: dict[str, Any] | None  # Result store metadata for frontend


class AgentState(TypedDict, total=False):
    user_query: str
    target_db_path: str
    intent: Intent
    intent_reason: str
    messages: Annotated[list[dict[str, Any]], operator.add]
    schema_context: str
    user_semantic_context: str
    context_type: ContextType
    needs_semantic_context: bool
    uploaded_files: list[str]
    uploaded_file_data: list[dict[str, Any]]
    registered_tables: list[str]
    retrieved_context: list[dict[str, Any]]
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
    expected_keywords: list[str]
    file_cache: dict[str, Any]  # Session-level CSV cache: hash_key -> metadata
    skipped_tables: list[str]  # Tables skipped due to caching
    table_contexts: dict[
        str, str
    ]  # table_name → user-provided business context (from pair upload)
    xml_database_context: str  # Full <database_context> XML block for SQL agent
    sql_retry_count: int  # SQL self-correction retry counter (0-2)
    sql_last_error: str | None  # Error message from last SQL failure
    # Plan-and-Execute additions
    task_plan: list[TaskState]  # Output from task_planner
    task_results: Annotated[list[TaskState], operator.add]  # Fan-in from workers
    aggregate_analysis: dict[str, Any]  # Combined analysis from parallel tasks
    execution_mode: ExecutionMode  # Router decision: single/parallel/linear
    visualization: dict[str, Any]  # Visualization data from nested sequential execution
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


class GraphInputState(TypedDict, total=False):
    user_query: str
    target_db_path: str
    user_semantic_context: str
    uploaded_files: list[str]
    uploaded_file_data: list[dict[str, Any]]
    thread_id: str  # Optional: for session memory scoping


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
    task_plan: list[TaskState]
    execution_mode: ExecutionMode
    aggregate_analysis: dict[str, Any]
    tool_history: list[dict[str, Any]]
    response_mode: ResponseMode


class ReportSection(TypedDict, total=False):
    section_id: str
    title: str
    analysis_query: str
    sql_result: dict[str, Any]
    result_ref: dict[str, Any] | None
    visualization: dict[str, Any] | None
    narrative: str
    status: Literal["pending", "done", "failed"]
    error: str | None
    generated_sql: str
    validated_sql: str


class ReportPlan(TypedDict, total=False):
    title: str
    executive_summary_instruction: str
    sections: list[ReportSection]
    conclusion_instruction: str
