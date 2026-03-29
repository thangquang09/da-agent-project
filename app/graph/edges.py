from __future__ import annotations

from typing import Literal

from app.graph.state import AgentState


def route_after_intent(state: AgentState) -> Literal["get_schema", "synthesize_answer"]:
    intent = state.get("intent", "unknown")
    if intent == "sql":
        return "get_schema"
    return "synthesize_answer"


def route_after_sql_validation(state: AgentState) -> Literal["execute_sql_node", "synthesize_answer"]:
    if state.get("errors"):
        return "synthesize_answer"
    return "execute_sql_node"

