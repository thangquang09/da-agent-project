from __future__ import annotations

import sqlite3

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
    detect_context_type,
    execute_sql_node,
    generate_sql,
    get_schema,
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

    builder.add_edge(START, "detect_context_type")
    builder.add_conditional_edges(
        "detect_context_type",
        route_after_context_detection,
        {
            "process_uploaded_files": "process_uploaded_files",
            "route_intent": "route_intent",
        },
    )
    builder.add_edge("process_uploaded_files", "route_intent")
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
    builder.add_edge("synthesize_answer", END)

    return builder.compile(checkpointer=checkpointer or InMemorySaver())


def _sql_worker_wrapper(task_state: dict) -> dict:
    """
    Wrapper node that runs SQL worker and returns result for accumulation.

    This wrapper properly isolates the worker subgraph execution and returns
    only the task result to be added to task_results via operator.add.
    """
    from app.graph.sql_worker_graph import get_sql_worker_graph

    worker = get_sql_worker_graph()

    # Run the worker subgraph
    result = worker.invoke(task_state)

    # Return the task result wrapped for accumulation
    # The task_results field uses Annotated[list, operator.add]
    return {"task_results": [result]}


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
        standalone_visualization_worker,
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
            "route_intent": "route_intent",
        },
    )
    builder.add_edge("process_uploaded_files", "route_intent")

    # Intent routing with Plan-and-Execute
    builder.add_conditional_edges(
        "route_intent",
        route_to_execution_mode,
        {
            "task_planner": "task_planner",  # SQL/mixed -> task planner
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

    # Final synthesis
    builder.add_edge("synthesize_answer", END)

    return builder.compile(checkpointer=checkpointer or InMemorySaver())
