from __future__ import annotations

from typing import Literal

from app.graph.state import AgentState


def route_after_context_detection(
    state: AgentState,
) -> Literal["process_uploaded_files", "route_intent"]:
    """
    After context detection, check if there are uploaded files to process.
    If yes, route to process_uploaded_files. Otherwise, go directly to route_intent.
    """
    uploaded_file_data = state.get("uploaded_file_data", [])
    if uploaded_file_data:
        return "process_uploaded_files"
    return "route_intent"


def route_after_process_files(state: AgentState) -> Literal["route_intent"]:
    """
    After processing uploaded files, always route to route_intent.
    """
    return "route_intent"


def route_after_intent(
    state: AgentState,
) -> Literal["get_schema", "retrieve_context_node", "synthesize_answer"]:
    intent = state.get("intent", "unknown")
    if intent in {"sql", "mixed"}:
        return "get_schema"
    if intent == "unknown":
        return "synthesize_answer"
    return "retrieve_context_node"


def route_after_sql_validation(
    state: AgentState,
) -> Literal[
    "generate_sql", "execute_sql_node", "retrieve_context_node", "synthesize_answer"
]:
    """Route after SQL validation with self-correction support.

    If validation fails and we haven't exceeded max retries, route back to generate_sql.
    Otherwise, proceed to error handling or execution.
    """
    errors = state.get("errors", [])
    retry_count = state.get("sql_retry_count", 0)
    max_retries = 2

    # Check for SQL validation errors
    validation_errors = [
        e for e in errors if e.get("category") == "SQL_VALIDATION_ERROR"
    ]

    if validation_errors:
        # Check if we should retry
        if retry_count < max_retries:
            # Will route back to generate_sql for self-correction
            return "generate_sql"

        # Max retries reached - proceed to error handling
        if state.get("intent") == "mixed":
            return "retrieve_context_node"
        return "synthesize_answer"

    # No validation errors - proceed to execution
    return "execute_sql_node"


def route_after_analysis(
    state: AgentState,
) -> Literal["retrieve_context_node", "synthesize_answer"]:
    if state.get("intent") == "mixed":
        return "retrieve_context_node"
    return "synthesize_answer"


def route_after_sql_execution(
    state: AgentState,
) -> Literal["generate_sql", "analyze_result"]:
    """Route after SQL execution with self-correction support.

    If execution fails with a retryable error and we haven't exceeded max retries,
    route back to generate_sql. Otherwise, proceed to analysis.
    """
    errors = state.get("errors", [])
    retry_count = state.get("sql_retry_count", 0)
    max_retries = 2

    # Check for SQL execution errors
    execution_errors = [e for e in errors if e.get("category") == "SQL_EXECUTION_ERROR"]

    if execution_errors:
        last_error = execution_errors[-1]

        # Check if error is retryable
        if not last_error.get("retryable", False):
            # Non-retryable error - proceed to analysis with error
            return "analyze_result"

        # Check retry limit
        if retry_count < max_retries:
            return "generate_sql"

    # No errors or max retries reached - proceed to analysis
    return "analyze_result"
