from __future__ import annotations

import sqlite3

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from app.graph.edges import (
    route_after_analysis,
    route_after_context_detection,
    route_after_intent,
    route_after_process_files,
    route_after_sql_execution,
    route_after_sql_validation,
)
from app.graph.nodes import (
    analyze_result,
    detect_context_type,
    execute_sql_node,
    generate_sql,
    get_schema,
    process_uploaded_files,
    retrieve_context_node,
    route_intent,
    synthesize_answer,
    validate_sql_node,
)
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
