from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict


Intent = Literal["sql", "rag", "mixed", "unknown"]
Confidence = Literal["high", "medium", "low"]


class AnswerPayload(TypedDict, total=False):
    answer: str
    evidence: list[str]
    confidence: Confidence
    used_tools: list[str]
    generated_sql: str


class AgentState(TypedDict, total=False):
    user_query: str
    intent: Intent
    intent_reason: str
    messages: Annotated[list[dict[str, Any]], operator.add]
    schema_context: str
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


class GraphInputState(TypedDict):
    user_query: str


class GraphOutputState(TypedDict, total=False):
    final_answer: str
    final_payload: AnswerPayload
    run_id: str
