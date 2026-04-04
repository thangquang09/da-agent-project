from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    capture_action_node,
    compact_and_save_memory,
    inject_session_context,
    leader_agent,
    process_uploaded_files,
)
from app.graph.state import AgentState, GraphInputState, GraphOutputState
from app.observability import get_current_tracer


def _instrument_node(node_name: str, fn, observation_type: str = "span"):  # noqa: ANN001
    def _wrapped(state: AgentState) -> AgentState:
        tracer = get_current_tracer()
        if tracer is None:
            return fn(state)
        scope = tracer.start_node(
            node_name=node_name,
            state=state,
            observation_type=observation_type,
        )
        try:
            update = fn(state)
        except Exception as exc:  # noqa: BLE001
            tracer.end_node(scope, error=exc)
            raise
        tracer.end_node(scope, update=update)
        return update

    return _wrapped


def build_sql_v3_graph(checkpointer=None):
    """
    Leader-first runtime graph for DA Agent Lab.

    Flow:
    process_uploaded_files -> inject_session_context -> leader_agent
    -> capture_action_node -> compact_and_save_memory
    """
    builder = StateGraph(
        AgentState,
        input_schema=GraphInputState,
        output_schema=GraphOutputState,
    )

    builder.add_node(
        "process_uploaded_files",
        _instrument_node("process_uploaded_files", process_uploaded_files, "tool"),
    )
    builder.add_node(
        "inject_session_context",
        _instrument_node("inject_session_context", inject_session_context, "memory"),
    )
    builder.add_node(
        "leader_agent",
        _instrument_node("leader_agent", leader_agent, "agent"),
    )
    builder.add_node(
        "capture_action_node",
        _instrument_node("capture_action_node", capture_action_node, "memory"),
    )
    builder.add_node(
        "compact_and_save_memory",
        _instrument_node("compact_and_save_memory", compact_and_save_memory, "memory"),
    )

    builder.add_edge(START, "process_uploaded_files")
    builder.add_edge("process_uploaded_files", "inject_session_context")
    builder.add_edge("inject_session_context", "leader_agent")
    builder.add_edge("leader_agent", "capture_action_node")
    builder.add_edge("capture_action_node", "compact_and_save_memory")
    builder.add_edge("compact_and_save_memory", END)

    return builder.compile(checkpointer=checkpointer or InMemorySaver())
