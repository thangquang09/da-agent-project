from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from app.config import load_settings
from app.graph.sql_worker_graph import get_sql_worker_graph
from app.graph.state import AgentState, ReportPlan, ReportSection
from app.llm import LLMClient
from app.logger import logger
from app.observability import get_current_tracer
from app.prompts import prompt_manager


def _instrument_node(node_name: str, fn):  # noqa: ANN001
    def _wrapped(state: AgentState) -> AgentState:
        tracer = get_current_tracer()
        if tracer is None:
            return fn(state)
        scope = tracer.start_node(
            node_name=node_name,
            state=state,
            observation_type="chain",
        )
        try:
            update = fn(state)
        except Exception as exc:  # noqa: BLE001
            tracer.end_node(scope, error=exc)
            raise
        tracer.end_node(scope, update=update)
        return update

    return _wrapped


def _extract_first_json_object(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _default_report_plan(query: str) -> ReportPlan:
    return {
        "title": f"Report: {query[:80]}".strip(),
        "executive_summary_instruction": "Summarize the most important findings from the available data.",
        "sections": [
            {
                "section_id": "1",
                "title": "Overview",
                "analysis_query": query,
                "status": "pending",
            },
            {
                "section_id": "2",
                "title": "Key Breakdown",
                "analysis_query": f"Provide a useful breakdown for: {query}",
                "status": "pending",
            },
        ],
        "conclusion_instruction": "Conclude with grounded findings and limitations.",
    }


def _section_requires_visualization(section: ReportSection) -> bool:
    text = f"{section.get('title', '')} {section.get('analysis_query', '')}".lower()
    return any(token in text for token in ("chart", "visual", "graph", "biểu đồ", "plot"))


def report_planner_node(state: AgentState) -> AgentState:
    query = state.get("report_request") or state.get("user_query", "")
    settings = load_settings()
    messages = prompt_manager.report_planner_messages(
        query=query,
        session_context=state.get("session_context", ""),
        xml_database_context=state.get("xml_database_context", ""),
    )

    try:
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=messages,
            model=settings.model_report_planner,
            temperature=0.0,
            stream=False,
        )
        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        parsed = _extract_first_json_object(content)
        plan = parsed if parsed and isinstance(parsed.get("sections"), list) else _default_report_plan(query)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Report planner failed: {error}", error=str(exc))
        plan = _default_report_plan(query)

    sections: list[ReportSection] = []
    for idx, raw in enumerate(plan.get("sections", []), start=1):
        if not isinstance(raw, dict):
            continue
        analysis_query = str(raw.get("analysis_query", "")).strip()
        if not analysis_query:
            continue
        sections.append(
            {
                "section_id": str(raw.get("section_id", idx)),
                "title": str(raw.get("title", f"Section {idx}")).strip() or f"Section {idx}",
                "analysis_query": analysis_query,
                "status": "pending",
            }
        )

    if not sections:
        plan = _default_report_plan(query)
        sections = plan["sections"]
    else:
        plan["sections"] = sections[:5]

    return {
        "report_plan": plan,
        "report_sections": plan.get("sections", []),
        "report_status": "executing",
        "tool_history": [
            {
                "tool": "report_planner",
                "status": "ok",
                "section_count": len(plan.get("sections", [])),
            }
        ],
    }


def _run_report_section(state: AgentState, section: ReportSection) -> ReportSection:
    worker = get_sql_worker_graph()
    task_input: dict[str, Any] = {
        "task_id": section.get("section_id", "1"),
        "query": section.get("analysis_query", ""),
        "target_db_path": state.get("target_db_path", ""),
        "schema_context": state.get("schema_context", ""),
        "session_context": state.get("session_context", ""),
        "xml_database_context": state.get("xml_database_context", ""),
        "status": "pending",
        "requires_visualization": _section_requires_visualization(section),
        "run_id": state.get("run_id", ""),
        "thread_id": state.get("thread_id", ""),
    }
    result = worker.invoke(task_input)
    status = "done" if result.get("status") == "success" else "failed"
    return {
        "section_id": section.get("section_id", "1"),
        "title": section.get("title", "Section"),
        "analysis_query": section.get("analysis_query", ""),
        "sql_result": result.get("sql_result", {}),
        "result_ref": result.get("result_ref"),
        "visualization": result.get("visualization"),
        "status": status,
        "error": result.get("error"),
        "generated_sql": result.get("generated_sql", ""),
        "validated_sql": result.get("validated_sql", ""),
    }


def report_executor_node(state: AgentState) -> AgentState:
    sections = state.get("report_sections") or state.get("report_plan", {}).get("sections", [])
    if not sections:
        return {
            "report_status": "failed",
            "errors": [
                {
                    "category": "REPORT_EXECUTION_ERROR",
                    "message": "No report sections available for execution.",
                }
            ],
        }

    with ThreadPoolExecutor(max_workers=min(len(sections), 4)) as executor:
        completed_sections = list(
            executor.map(lambda section: _run_report_section(state, section), sections)
        )

    failed_sections = [section for section in completed_sections if section.get("status") == "failed"]
    return {
        "report_sections": completed_sections,
        "report_status": "writing",
        "errors": [
            {
                "category": "REPORT_SECTION_ERROR",
                "message": str(section.get("error", "Unknown report section failure")),
                "section_id": section.get("section_id"),
            }
            for section in failed_sections
        ],
        "tool_history": [
            {
                "tool": "report_executor",
                "status": "ok",
                "section_count": len(completed_sections),
                "failed_sections": len(failed_sections),
            }
        ],
    }


def report_writer_node(state: AgentState) -> AgentState:
    settings = load_settings()
    report_plan = json.dumps(state.get("report_plan", {}), ensure_ascii=False, indent=2, default=str)
    section_results = json.dumps(state.get("report_sections", []), ensure_ascii=False, indent=2, default=str)
    messages = prompt_manager.report_writer_messages(
        query=state.get("report_request") or state.get("user_query", ""),
        report_plan=report_plan,
        section_results=section_results,
        critic_feedback=state.get("critic_feedback", ""),
    )

    report_draft = ""
    try:
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=messages,
            model=settings.model_report_writer,
            temperature=0.2,
            stream=False,
        )
        report_draft = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Report writer failed: {error}", error=str(exc))

    if not report_draft:
        sections = state.get("report_sections", [])
        lines = [f"# {state.get('report_plan', {}).get('title', 'Report')}"]
        for section in sections:
            lines.append(f"## {section.get('title', 'Section')}")
            if section.get("status") == "failed":
                lines.append(f"Section execution failed: {section.get('error', 'Unknown error')}")
            else:
                row_count = section.get("sql_result", {}).get("row_count", 0)
                lines.append(f"Retrieved {row_count} rows for this section.")
        report_draft = "\n\n".join(lines)

    return {
        "report_draft": report_draft,
        "report_status": "critiquing",
        "tool_history": [
            {
                "tool": "report_writer",
                "status": "ok",
                "draft_length": len(report_draft),
            }
        ],
    }


def report_critic_node(state: AgentState) -> AgentState:
    settings = load_settings()
    section_results = json.dumps(state.get("report_sections", []), ensure_ascii=False, indent=2, default=str)
    report_draft = state.get("report_draft", "")
    previous_feedback_hash = state.get("report_feedback_hash", "")
    previous_draft_hash = state.get("report_draft_hash", "")
    current_draft_hash = _stable_hash(report_draft)

    verdict = "APPROVED"
    issues: list[str] = []
    summary = "Draft is grounded."
    try:
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=prompt_manager.report_critic_messages(
                query=state.get("report_request") or state.get("user_query", ""),
                section_results=section_results,
                report_draft=report_draft,
            ),
            model=settings.model_report_critic,
            temperature=0.0,
            stream=False,
        )
        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        parsed = _extract_first_json_object(content) or {}
        verdict = str(parsed.get("verdict", "APPROVED")).upper()
        issues = [str(item).strip() for item in parsed.get("issues", []) if str(item).strip()]
        summary = str(parsed.get("summary", summary)).strip() or summary
    except Exception as exc:  # noqa: BLE001
        logger.warning("Report critic failed: {error}", error=str(exc))

    feedback = summary
    if issues:
        feedback = f"{summary}\n- " + "\n- ".join(issues)
    feedback_hash = _stable_hash(feedback)
    critic_iteration = int(state.get("critic_iteration", 0) or 0) + 1

    should_revise = (
        verdict == "REVISE"
        and critic_iteration < 2
        and feedback_hash != previous_feedback_hash
        and current_draft_hash != previous_draft_hash
    )
    return {
        "critic_feedback": feedback,
        "critic_iteration": critic_iteration,
        "report_feedback_hash": feedback_hash,
        "report_draft_hash": current_draft_hash,
        "report_status": "writing" if should_revise else "done",
        "critic_decision": "revise" if should_revise else "finalize",
        "tool_history": [
            {
                "tool": "report_critic",
                "status": "ok",
                "verdict": verdict,
                "iteration": critic_iteration,
                "issue_count": len(issues),
            }
        ],
    }


def _critic_router(state: AgentState) -> Literal["report_writer", "report_finalize"]:
    return "report_writer" if state.get("critic_decision") == "revise" else "report_finalize"


def report_finalize_node(state: AgentState) -> AgentState:
    report_markdown = state.get("report_draft", "").strip()
    plan_title = state.get("report_plan", {}).get("title", "Report")
    errors = state.get("errors", [])
    answer = report_markdown or f"# {plan_title}\n\nNo report content was generated."
    payload = {
        "answer": answer,
        "report_markdown": answer,
        "evidence": [
            "intent=sql",
            f"rows={sum(section.get('sql_result', {}).get('row_count', 0) for section in state.get('report_sections', []))}",
            "context_chunks=0",
        ],
        "confidence": "medium" if errors else "high",
        "used_tools": ["generate_report"],
        "generated_sql": "\n\n---\n\n".join(
            section.get("validated_sql") or section.get("generated_sql", "")
            for section in state.get("report_sections", [])
            if section.get("validated_sql") or section.get("generated_sql")
        ),
        "error_categories": [str(item.get("category", "UNKNOWN")) for item in errors],
        "step_count": state.get("step_count", 0) + 1,
        "context_type": state.get("context_type", "default"),
        "sql_rows": [],
        "sql_row_count": sum(
            section.get("sql_result", {}).get("row_count", 0)
            for section in state.get("report_sections", [])
        ),
        "result_metadata": None,
    }
    return {
        "final_answer": answer,
        "final_payload": payload,
        "report_final": answer,
        "report_status": "done",
        "intent": "sql",
        "confidence": payload["confidence"],
        "response_mode": "report",
        "tool_history": [
            {
                "tool": "report_finalize",
                "status": "ok",
                "section_count": len(state.get("report_sections", [])),
            }
        ],
        "step_count": state.get("step_count", 0) + 1,
    }


def build_report_subgraph():
    builder = StateGraph(AgentState)
    builder.add_node("report_planner", _instrument_node("report_planner_node", report_planner_node))
    builder.add_node("report_executor", _instrument_node("report_executor_node", report_executor_node))
    builder.add_node("report_writer", _instrument_node("report_writer_node", report_writer_node))
    builder.add_node("report_critic", _instrument_node("report_critic_node", report_critic_node))
    builder.add_node("report_finalize", _instrument_node("report_finalize_node", report_finalize_node))

    builder.add_edge(START, "report_planner")
    builder.add_edge("report_planner", "report_executor")
    builder.add_edge("report_executor", "report_writer")
    builder.add_edge("report_writer", "report_critic")
    builder.add_conditional_edges(
        "report_critic",
        _critic_router,
        {
            "report_writer": "report_writer",
            "report_finalize": "report_finalize",
        },
    )
    builder.add_edge("report_finalize", END)
    return builder.compile()
