from __future__ import annotations

from typing import Literal

from app.graph.state import AgentState


def route_after_context_detection(state: AgentState) -> Literal["route_intent"]:
    """
    After context detection, always route to route_intent.
    The context_type has been stored in state for later use.
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
) -> Literal["execute_sql_node", "retrieve_context_node", "synthesize_answer"]:
    if state.get("errors"):
        if state.get("intent") == "mixed":
            return "retrieve_context_node"
        return "synthesize_answer"
    return "execute_sql_node"


def route_after_analysis(
    state: AgentState,
) -> Literal["retrieve_context_node", "synthesize_answer"]:
    if state.get("intent") == "mixed":
        return "retrieve_context_node"
    return "synthesize_answer"
