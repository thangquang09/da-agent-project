from __future__ import annotations

from typing import Literal

from langgraph.types import Send

from app.graph.state import AgentState, TaskState


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

    # Check only the most recent error (last in accumulated list)
    last_error = errors[-1] if errors else None

    if last_error and last_error.get("category") == "SQL_VALIDATION_ERROR":
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

    # Check only the most recent error (last in accumulated list)
    last_error = errors[-1] if errors else None

    if last_error and last_error.get("category") == "SQL_EXECUTION_ERROR":
        # Check if error is retryable
        if not last_error.get("retryable", False):
            # Non-retryable error - proceed to analysis with error
            return "analyze_result"

        # Check retry limit
        if retry_count < max_retries:
            return "generate_sql"

    # No errors or max retries reached - proceed to analysis
    return "analyze_result"


def route_to_execution_mode(
    state: AgentState,
) -> Literal[
    "task_planner", "get_schema", "retrieve_context_node", "synthesize_answer"
]:
    """
    Router after intent detection that decides execution strategy.

    For SQL/mixed queries, route to task_planner to potentially parallelize.
    For RAG queries, route directly to retrieval.
    For unknown, go to synthesis.
    """
    intent = state.get("intent", "unknown")

    if intent in {"sql", "mixed"}:
        # Route to task_planner which will decide single vs parallel
        return "task_planner"
    if intent == "rag":
        return "retrieve_context_node"

    return "synthesize_answer"


def route_after_planning(
    state: AgentState,
) -> list[Send] | Literal["aggregate_results", "sql_worker", "synthesize_answer"]:
    """
    Fan-out router using Send API for task execution.

    If task_plan has tasks, create Send objects for workers.
    Tasks are always executed regardless of execution_mode.
    execution_mode may influence future optimizations but does not block execution.
    """
    task_plan = state.get("task_plan", [])
    execution_mode = state.get("execution_mode", "linear")

    if not task_plan:
        # No tasks planned - go to synthesis with error
        return "synthesize_answer"

    # Always execute tasks if present
    # execution_mode is informational; tasks must be processed
    if len(task_plan) >= 1:
        sends = []
        for task in task_plan:
            send_state = {
                "task_id": str(task.get("task_id", "unknown")),
                "task_type": str(task.get("type", "sql_query")),
                "query": str(task.get("query", "")),
                "target_db_path": str(task.get("target_db_path"))
                if task.get("target_db_path")
                else "",
                "schema_context": str(task.get("task_context", "")),
                "status": "pending",
            }
            sends.append(Send("sql_worker", send_state))

        logger.info(
            "Routing {count} task(s) to sql_worker (mode={mode})",
            count=len(task_plan),
            mode=execution_mode,
        )
        return sends

    # No tasks - should not reach here, but fallback
    return "synthesize_answer"


def route_after_worker_execution(
    state: AgentState,
) -> Literal["aggregate_results", "synthesize_answer"]:
    """
    Route after parallel worker execution.

    Always go to aggregation to combine results, even for single tasks
    (provides consistent handling).
    """
    task_results = state.get("task_results", [])

    if task_results:
        return "aggregate_results"

    # No results - something went wrong
    return "synthesize_answer"
