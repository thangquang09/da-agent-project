from __future__ import annotations

import sqlite3
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from app.graph.edges import (
    route_after_analysis,
    route_after_context_detection,
    route_after_intent,
    route_after_planning,
    route_after_process_files,
    route_after_sql_execution,
    route_after_sql_validation,
    route_to_execution_mode,
    route_after_worker_execution,
)
from app.graph.nodes import (
    aggregate_results,
    analyze_result,
    capture_action_node,
    compact_and_save_memory,
    detect_context_type,
    detect_continuity_node,
    execute_sql_node,
    generate_sql,
    get_schema,
    inject_session_context,
    process_uploaded_files,
    retrieve_context_node,
    route_intent,
    synthesize_answer,
    task_planner,
    validate_sql_node,
)
from app.graph.sql_worker_graph import get_sql_worker_graph
from app.graph.standalone_visualization import standalone_visualization_worker
from app.graph.state import AgentState, GraphInputState, GraphOutputState
from app.observability import get_current_tracer


def _instrument_node(node_name: str, fn, observation_type: str = "span"):  # noqa: ANN001
    def _wrapped(state: AgentState) -> AgentState:
        tracer = get_current_tracer()
        if tracer is None:
            return fn(state)
        scope = tracer.start_node(
            node_name=node_name, state=state, observation_type=observation_type
        )
        try:
            update = fn(state)
        except Exception as exc:  # noqa: BLE001
            tracer.end_node(scope, error=exc)
            raise
        tracer.end_node(scope, update=update)
        return update

    return _wrapped


def build_sql_v1_graph(checkpointer=None):
    builder = StateGraph(
        AgentState,
        input_schema=GraphInputState,
        output_schema=GraphOutputState,
    )

    builder.add_node(
        "detect_context_type",
        _instrument_node("detect_context_type", detect_context_type, "classifier"),
    )
    builder.add_node(
        "process_uploaded_files",
        _instrument_node("process_uploaded_files", process_uploaded_files, "tool"),
    )
    builder.add_node(
        "detect_continuity_node",
        _instrument_node("detect_continuity_node", detect_continuity_node, "memory"),
    )
    builder.add_node(
        "inject_session_context",
        _instrument_node("inject_session_context", inject_session_context, "memory"),
    )
    builder.add_node(
        "route_intent", _instrument_node("route_intent", route_intent, "agent")
    )
    builder.add_node(
        "get_schema", _instrument_node("get_schema", get_schema, "retriever")
    )
    builder.add_node(
        "generate_sql",
        _instrument_node("generate_sql", generate_sql, "generation"),
        retry_policy=RetryPolicy(max_attempts=2),
    )
    builder.add_node(
        "validate_sql_node",
        _instrument_node("validate_sql_node", validate_sql_node, "guardrail"),
    )
    builder.add_node(
        "execute_sql_node",
        _instrument_node("execute_sql_node", execute_sql_node, "tool"),
    )
    builder.add_node(
        "analyze_result", _instrument_node("analyze_result", analyze_result, "chain")
    )
    builder.add_node(
        "retrieve_context_node",
        _instrument_node("retrieve_context_node", retrieve_context_node, "retriever"),
    )
    builder.add_node(
        "synthesize_answer",
        _instrument_node("synthesize_answer", synthesize_answer, "generation"),
    )
    builder.add_node(
        "capture_action_node",
        _instrument_node("capture_action_node", capture_action_node, "memory"),
    )
    builder.add_node(
        "compact_and_save_memory",
        _instrument_node("compact_and_save_memory", compact_and_save_memory, "memory"),
    )

    # Flow: START → detect_context_type → (process_uploaded_files OR inject_session_context)
    builder.add_edge(START, "detect_context_type")
    builder.add_conditional_edges(
        "detect_context_type",
        route_after_context_detection,
        {
            "process_uploaded_files": "process_uploaded_files",
            "inject_session_context": "inject_session_context",
        },
    )
    builder.add_edge("process_uploaded_files", "inject_session_context")
    builder.add_edge("inject_session_context", "detect_continuity_node")
    builder.add_edge("detect_continuity_node", "route_intent")
    builder.add_conditional_edges(
        "route_intent",
        route_after_intent,
        {
            "get_schema": "get_schema",
            "retrieve_context_node": "retrieve_context_node",
            "synthesize_answer": "synthesize_answer",
        },
    )

    builder.add_edge("get_schema", "generate_sql")
    builder.add_edge("generate_sql", "validate_sql_node")
    builder.add_conditional_edges(
        "validate_sql_node",
        route_after_sql_validation,
        {
            "generate_sql": "generate_sql",  # Self-correction loop
            "execute_sql_node": "execute_sql_node",
            "retrieve_context_node": "retrieve_context_node",
            "synthesize_answer": "synthesize_answer",
        },
    )
    builder.add_conditional_edges(
        "execute_sql_node",
        route_after_sql_execution,
        {
            "generate_sql": "generate_sql",  # Self-correction loop
            "analyze_result": "analyze_result",
        },
    )
    builder.add_conditional_edges(
        "analyze_result",
        route_after_analysis,
        {
            "retrieve_context_node": "retrieve_context_node",
            "synthesize_answer": "synthesize_answer",
        },
    )
    builder.add_edge("retrieve_context_node", "synthesize_answer")
    builder.add_edge("synthesize_answer", "capture_action_node")
    builder.add_edge("capture_action_node", "compact_and_save_memory")
    builder.add_edge("compact_and_save_memory", END)

    return builder.compile(checkpointer=checkpointer or InMemorySaver())


def _sql_worker_wrapper(state: dict) -> dict:
    """
    Wrapper node that runs SQL worker and returns result for accumulation.

    Handles two invocation modes:
    1. Via Send API (from route_after_planning): receives TaskState dict with task_id, query, etc.
    2. Direct routing (from route_to_execution_mode): receives full AgentState, needs to build TaskState.

    Also flattens sql_result, generated_sql, validated_sql into root state fields
    so synthesize_answer can access them when aggregate_results is bypassed.
    """
    from app.graph.sql_worker_graph import get_sql_worker_graph

    worker = get_sql_worker_graph()

    # Detect invocation mode
    # Intentional duck-typing: Send API passes TaskState (has task_id),
    # direct routing passes full AgentState (no task_id). This avoids
    # coupling to a specific type check and works across both paths.
    if "task_id" in state:
        # Send API mode: already a TaskState
        task_state = state
    else:
        # Direct mode: build TaskState from AgentState
        task_state = {
            "task_id": "direct",
            "task_type": "sql_query",
            "query": state.get("user_query", ""),
            "target_db_path": state.get("target_db_path", ""),
            "schema_context": state.get("schema_context", ""),
            "session_context": state.get("session_context", ""),
            "xml_database_context": state.get("xml_database_context", ""),
            "status": "pending",
            "requires_visualization": False,
        }
        # Handle continuity
        continuity_ctx = state.get("continuity_context", {})
        if continuity_ctx.get("is_continuation"):
            inherited = continuity_ctx.get("inherited_action", {})
            if inherited.get("base_sql"):
                task_state["inherited_sql"] = inherited["base_sql"]
                task_state["parameter_changes"] = continuity_ctx.get(
                    "parameter_changes", {}
                )
                task_state["requires_visualization"] = inherited.get(
                    "add_visualization", False
                )

    # Run the worker subgraph
    result = worker.invoke(task_state)

    # Extract tool_history from subgraph nodes and merge into parent AgentState
    # Each subgraph node returns its own tool_history entry; they accumulate via operator.add
    subgraph_tool_history = result.get("tool_history", [])

    # Flatten SQL data for synthesize_answer compatibility (when aggregate_results is bypassed)
    # Only write root-level fields in direct mode (single worker).
    # In parallel mode, data flows through task_results -> aggregate_results,
    # so writing root fields here would cause INVALID_CONCURRENT_GRAPH_UPDATE.
    is_direct_mode = "task_id" in state and state.get("task_id") == "direct"

    update: dict[str, Any] = {
        "task_results": [result],
        "tool_history": subgraph_tool_history,
    }

    if is_direct_mode:
        # Direct mode: flatten everything to root state for synthesize_answer
        sql_result = result.get("sql_result", {})
        validated_sql = result.get("validated_sql", "")
        generated_sql = result.get("generated_sql", "")
        visualization = result.get("visualization")
        result_ref = result.get("result_ref")

        update["sql_result"] = sql_result
        update["generated_sql"] = generated_sql
        update["validated_sql"] = validated_sql
        if visualization:
            update["visualization"] = visualization
        if result_ref:
            update["result_ref"] = result_ref
    # In parallel mode: only write Annotated fields (task_results, tool_history).
    # aggregate_results will flatten sql_result, result_ref, visualization after all workers complete.

    return update


def _standalone_viz_wrapper(state: dict) -> dict[str, Any]:
    """Wrapper for standalone_visualization that accumulates results via task_results.

    Prevents concurrent write conflicts when multiple workers run in parallel via Send API.
    aggregate_results will extract visualization from task_results and write to root state.
    """
    result = standalone_visualization_worker(state)
    return {
        "task_results": [result],
        "tool_history": result.get("tool_history", []),
    }


def build_sql_v2_graph(checkpointer=None):
    """
    Version 2 with Plan-and-Execute architecture using Send API.

    This graph introduces:
    - task_planner: Decomposes queries into parallelizable sub-tasks
    - sql_worker: Subgraph for executing individual tasks in parallel
    - aggregate_results: Fan-in to combine parallel task results

    Routing logic:
    - If task_planner outputs 1 task: routes through single worker (linear)
    - If task_planner outputs >1 tasks: fans out to parallel workers (parallel)
    """
    builder = StateGraph(
        AgentState,
        input_schema=GraphInputState,
        output_schema=GraphOutputState,
    )

    # Add existing nodes
    builder.add_node(
        "detect_context_type",
        _instrument_node("detect_context_type", detect_context_type, "classifier"),
    )
    builder.add_node(
        "process_uploaded_files",
        _instrument_node("process_uploaded_files", process_uploaded_files, "tool"),
    )
    builder.add_node(
        "detect_continuity_node",
        _instrument_node("detect_continuity_node", detect_continuity_node, "memory"),
    )
    builder.add_node(
        "inject_session_context",
        _instrument_node("inject_session_context", inject_session_context, "memory"),
    )
    builder.add_node(
        "route_intent", _instrument_node("route_intent", route_intent, "agent")
    )
    builder.add_node(
        "retrieve_context_node",
        _instrument_node("retrieve_context_node", retrieve_context_node, "retriever"),
    )
    builder.add_node(
        "synthesize_answer",
        _instrument_node("synthesize_answer", synthesize_answer, "generation"),
    )
    builder.add_node(
        "capture_action_node",
        _instrument_node("capture_action_node", capture_action_node, "memory"),
    )
    builder.add_node(
        "compact_and_save_memory",
        _instrument_node("compact_and_save_memory", compact_and_save_memory, "memory"),
    )

    # Add Plan-and-Execute nodes
    builder.add_node(
        "task_planner",
        _instrument_node("task_planner", task_planner, "planner"),
    )
    builder.add_node(
        "sql_worker",
        _sql_worker_wrapper,
    )
    builder.add_node(
        "standalone_visualization",
        _standalone_viz_wrapper,
    )
    builder.add_node(
        "aggregate_results",
        _instrument_node("aggregate_results", aggregate_results, "aggregator"),
    )

    # Context detection flow
    builder.add_edge(START, "detect_context_type")
    builder.add_conditional_edges(
        "detect_context_type",
        route_after_context_detection,
        {
            "process_uploaded_files": "process_uploaded_files",
            "inject_session_context": "inject_session_context",
        },
    )
    builder.add_edge("process_uploaded_files", "inject_session_context")
    builder.add_edge("inject_session_context", "detect_continuity_node")
    builder.add_edge("detect_continuity_node", "route_intent")

    # Intent routing with Plan-and-Execute
    builder.add_conditional_edges(
        "route_intent",
        route_to_execution_mode,
        {
            "task_planner": "task_planner",  # SQL/mixed -> task planner (planned mode)
            "sql_worker": "sql_worker",  # SQL/mixed -> direct worker (direct mode)
            "retrieve_context_node": "retrieve_context_node",  # RAG -> retrieval
            "synthesize_answer": "synthesize_answer",  # unknown -> synthesis
        },
    )

    # Plan-and-Execute flow
    builder.add_conditional_edges(
        "task_planner",
        route_after_planning,
        ["sql_worker", "standalone_visualization", "synthesize_answer"],
    )

    # Worker results fan-in
    builder.add_conditional_edges(
        "sql_worker",
        route_after_worker_execution,
        {
            "aggregate_results": "aggregate_results",
            "synthesize_answer": "synthesize_answer",
        },
    )

    # Standalone visualization goes directly to synthesis
    builder.add_edge("standalone_visualization", "aggregate_results")

    # Aggregation to synthesis
    builder.add_edge("aggregate_results", "synthesize_answer")

    # RAG flow
    builder.add_edge("retrieve_context_node", "synthesize_answer")

    # Final synthesis, action capture, and memory save
    builder.add_edge("synthesize_answer", "capture_action_node")
    builder.add_edge("capture_action_node", "compact_and_save_memory")
    builder.add_edge("compact_and_save_memory", END)

    return builder.compile(checkpointer=checkpointer or InMemorySaver())
