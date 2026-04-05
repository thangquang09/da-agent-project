from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    artifact_evaluator,
    capture_action_node,
    clarify_question_node,
    compact_and_save_memory,
    inject_session_context,
    leader_agent,
    process_uploaded_files,
)
from app.graph.report_subgraph import build_report_subgraph
from app.graph.state import AgentState, GraphInputState, GraphOutputState
from app.graph.task_grounder import task_grounder
from app.logger import logger
from app.observability import get_current_tracer


def _instrument_node(node_name: str, fn, observation_type: str = "span"):  # noqa: ANN001
    def _wrapped(state: AgentState) -> AgentState:
        tracer = get_current_tracer()
        # Bind user_query to logger context for debug file traceability
        user_query = state.get("user_query", "-") if isinstance(state, dict) else "-"
        effective_run_id = tracer.run_id if tracer else "-"
        with logger.contextualize(run_id=effective_run_id, node_name=node_name, task_id="-", user_query=str(user_query)):
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
    process_uploaded_files -> inject_session_context -> task_grounder
    -> leader_agent -> capture_action_node -> compact_and_save_memory
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
        "task_grounder",
        _instrument_node("task_grounder", task_grounder, "agent"),
    )
    builder.add_node(
        "leader_agent",
        _instrument_node("leader_agent", leader_agent, "agent"),
    )
    builder.add_node(
        "artifact_evaluator",
        _instrument_node("artifact_evaluator", artifact_evaluator, "agent"),
    )
    builder.add_node(
        "clarify_question_node",
        _instrument_node("clarify_question_node", clarify_question_node, "memory"),
    )
    builder.add_node("report_subgraph", build_report_subgraph())
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
    builder.add_edge("inject_session_context", "task_grounder")
    builder.add_edge("task_grounder", "leader_agent")
    builder.add_edge("leader_agent", "artifact_evaluator")
    builder.add_conditional_edges(
        "artifact_evaluator",
        _route_after_leader,
        {
            "leader_agent": "leader_agent",  # continue/retry — loop back
            "clarify_question_node": "clarify_question_node",  # wait_for_user — interrupt
            "report_subgraph": "report_subgraph",
            "capture_action_node": "capture_action_node",
        },
    )
    builder.add_edge("report_subgraph", "capture_action_node")
    builder.add_edge("capture_action_node", "compact_and_save_memory")
    builder.add_edge("compact_and_save_memory", END)
    builder.add_edge("clarify_question_node", END)

    return builder.compile(checkpointer=checkpointer or InMemorySaver())


def _route_after_leader(state: AgentState) -> str:
    """Route after artifact_evaluator.

    Decisions from artifact_evaluator:
    - "continue" / "retry" → loop back to leader_agent
    - "wait_for_user"      → halt and surface clarification question (interrupt)
    - "finalize"           → capture_action_node (or report_subgraph if report mode)
    """
    eval_decision = (state.get("artifact_evaluation") or {}).get("decision", "finalize")

    if eval_decision in ("continue", "retry"):
        return "leader_agent"  # loop back

    if eval_decision == "wait_for_user":
        return "clarify_question_node"  # interrupt and ask user

    # finalize — report mode goes to report pipeline, else capture
    if state.get("response_mode") == "report":
        return "report_subgraph"

    return "capture_action_node"
