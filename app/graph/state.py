from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict


Intent = Literal["sql", "rag", "mixed", "unknown"]
Confidence = Literal["high", "medium", "low"]
ContextType = Literal["user_provided", "csv_auto", "mixed", "default"]


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
