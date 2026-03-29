from __future__ import annotations

import sqlite3

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from app.graph.edges import route_after_intent, route_after_sql_validation
from app.graph.nodes import (
    analyze_result,
    execute_sql_node,
    generate_sql,
    get_schema,
    route_intent,
    synthesize_answer,
    validate_sql_node,
)
from app.graph.state import AgentState, GraphInputState, GraphOutputState


def build_sql_v1_graph(checkpointer=None):
    builder = StateGraph(
        AgentState,
        input_schema=GraphInputState,
        output_schema=GraphOutputState,
    )

    builder.add_node("route_intent", route_intent)
    builder.add_node("get_schema", get_schema)
    builder.add_node("generate_sql", generate_sql, retry_policy=RetryPolicy(max_attempts=2))
    builder.add_node("validate_sql_node", validate_sql_node)
    builder.add_node(
        "execute_sql_node",
        execute_sql_node,
        retry_policy=RetryPolicy(max_attempts=2, retry_on=sqlite3.OperationalError),
    )
    builder.add_node("analyze_result", analyze_result)
    builder.add_node("synthesize_answer", synthesize_answer)

    builder.add_edge(START, "route_intent")
    builder.add_conditional_edges(
        "route_intent",
        route_after_intent,
        {
            "get_schema": "get_schema",
            "synthesize_answer": "synthesize_answer",
        },
    )
    builder.add_edge("get_schema", "generate_sql")
    builder.add_edge("generate_sql", "validate_sql_node")
    builder.add_conditional_edges(
        "validate_sql_node",
        route_after_sql_validation,
        {
            "execute_sql_node": "execute_sql_node",
            "synthesize_answer": "synthesize_answer",
        },
    )
    builder.add_edge("execute_sql_node", "analyze_result")
    builder.add_edge("analyze_result", "synthesize_answer")
    builder.add_edge("synthesize_answer", END)

    return builder.compile(checkpointer=checkpointer or InMemorySaver())
