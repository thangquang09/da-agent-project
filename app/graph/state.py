from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict


Intent = Literal["sql", "rag", "mixed", "unknown"]
Confidence = Literal["high", "medium", "low"]
ContextType = Literal["user_provided", "csv_auto", "mixed", "default"]
TaskType = Literal["sql_query", "data_analysis", "context_lookup"]
ExecutionMode = Literal["single", "parallel", "linear"]


class TaskState(TypedDict, total=False):
    """State for individual task execution in parallel workers."""

    task_id: str
    task_type: TaskType
    query: str
    target_db_path: str
    schema_context: str
    generated_sql: str
    validated_sql: str
    sql_result: dict[str, Any]
    analysis_result: dict[str, Any]
    status: Literal["pending", "running", "success", "failed"]
    error: str | None
    execution_time_ms: float


class AnswerPayload(TypedDict, total=False):
    answer: str
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


class AgentState(TypedDict, total=False):
    user_query: str
    target_db_path: str
    intent: Intent
    intent_reason: str
    messages: Annotated[list[dict[str, Any]], operator.add]
    schema_context: str
    dataset_context: str
    user_semantic_context: str
    retrieved_dataset_context: list[dict[str, Any]]
    context_type: ContextType
    needs_semantic_context: bool
    detected_intent: list[str]
    uploaded_files: list[str]
    uploaded_file_data: list[dict[str, Any]]
    registered_tables: list[str]
    retrieved_context: list[dict[str, Any]]
    resolved_context: str
    conflict_notes: list[str]
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
    sql_retry_count: int  # SQL self-correction retry counter (0-2)
    sql_last_error: str | None  # Error message from last SQL failure
    # Plan-and-Execute additions
    task_plan: list[TaskState]  # Output from task_planner
    task_results: Annotated[list[TaskState], operator.add]  # Fan-in from workers
    aggregate_analysis: dict[str, Any]  # Combined analysis from parallel tasks
    execution_mode: ExecutionMode  # Router decision: single/parallel/linear


class GraphInputState(TypedDict, total=False):
    user_query: str
    target_db_path: str
    user_semantic_context: str
    uploaded_files: list[str]
    uploaded_file_data: list[dict[str, Any]]


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
