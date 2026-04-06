from __future__ import annotations

import base64
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from app.config import load_settings
from app.graph.sql_worker_graph import get_sql_worker_graph
from app.graph.state import AgentState, ReportPlan, ReportSection
from app.llm import LLMClient
from app.logger import logger
from app.observability import get_current_tracer
from app.prompts import prompt_manager
from app.tools.get_schema import get_schema_overview
from app.tools.visualization import get_visualization_service


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


def _strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    fenced = re.match(r"^```(?:markdown|md)?\s*([\s\S]*?)\s*```$", stripped, re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return stripped


def _normalize_heading_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _cleanup_report_markdown(text: str) -> str:
    cleaned = _strip_markdown_fences(text)
    lines = cleaned.splitlines()
    output: list[str] = []

    for line in lines:
        heading_match = re.match(r"^(#{2,6})\s+(.*)$", line.strip())
        if heading_match and output:
            previous = output[-1].strip()
            previous_match = re.match(r"^(#{2,6})\s+(.*)$", previous)
            if previous_match:
                same_text = _normalize_heading_text(previous_match.group(2)) == _normalize_heading_text(
                    heading_match.group(2)
                )
                if same_text:
                    continue
        output.append(line)

    return "\n".join(output).strip()


def _report_section_payload(section: ReportSection) -> dict[str, Any]:
    chart_image = section.get("chart_image") or {}
    image_data = chart_image.get("image_data")
    image_format = chart_image.get("image_format", "png")
    return {
        "section_id": section.get("section_id", ""),
        "title": section.get("title", ""),
        "insight_markdown": section.get("insight_markdown", ""),
        "chart_image": (
            {
                "success": bool(image_data),
                "image_data": image_data,
                "image_format": image_format,
                "execution_time_ms": ((section.get("visualization") or {}).get("execution_time_ms", 0.0)),
                "error": ((section.get("visualization") or {}).get("error")),
            }
            if image_data
            else None
        ),
        "chart_manifest": section.get("chart_manifest"),
        "limitations": section.get("limitations", []),
    }


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
        plan = (
            parsed
            if parsed and isinstance(parsed.get("sections"), list)
            else _default_report_plan(query)
        )
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
                "title": str(raw.get("title", f"Section {idx}")).strip()
                or f"Section {idx}",
                "analysis_query": analysis_query,
                "status": "pending",
                "analysis_status": "pending",
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


def _load_report_rows(section_result: dict[str, Any]) -> list[dict[str, Any]]:
    sql_result = section_result.get("sql_result", {})
    rows = sql_result.get("rows", [])
    if rows:
        return rows

    result_ref = section_result.get("result_ref") or {}
    full_data_path = result_ref.get("full_data_path")
    if not full_data_path:
        return []

    try:
        return json.loads(Path(full_data_path).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load report rows from result_ref: {error}", error=str(exc))
        return []


def _resolve_report_schema_context(state: AgentState) -> str:
    existing_schema = str(state.get("schema_context", "") or "").strip()
    if existing_schema:
        return existing_schema

    db_path = state.get("target_db_path")
    try:
        overview = get_schema_overview(db_path=Path(db_path) if db_path else None)
        return str(overview)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to resolve report schema context: {error}", error=str(exc))
        return ""


def _run_report_section(state: AgentState, section: ReportSection) -> ReportSection:
    worker = get_sql_worker_graph()
    schema_context = state.get("report_schema_context") or state.get("schema_context", "")
    task_input: dict[str, Any] = {
        "task_id": section.get("section_id", "1"),
        "query": section.get("analysis_query", ""),
        "target_db_path": state.get("target_db_path", ""),
        "schema_context": schema_context,
        "session_context": state.get("session_context", ""),
        "xml_database_context": state.get("xml_database_context", ""),
        "status": "pending",
        "requires_visualization": False,
        "run_id": state.get("run_id", ""),
        "thread_id": state.get("thread_id", ""),
    }
    result = worker.invoke(task_input)
    status = "done" if result.get("status") == "success" else "failed"
    report_section: ReportSection = {
        "section_id": section.get("section_id", "1"),
        "title": section.get("title", "Section"),
        "analysis_query": section.get("analysis_query", ""),
        "sql_result": result.get("sql_result", {}),
        "result_ref": result.get("result_ref"),
        "raw_result_ref": result.get("result_ref"),
        "status": status,
        "analysis_status": "failed" if status == "failed" else "pending",
        "error": result.get("error"),
        "generated_sql": result.get("generated_sql", ""),
        "validated_sql": result.get("validated_sql", ""),
    }

    if status == "failed":
        return report_section

    rows = _load_report_rows(report_section)
    analysis = get_visualization_service().generate_grounded_report_analysis(
        data_rows=rows,
        user_query=section.get("analysis_query", ""),
        section_title=section.get("title", "Section"),
    )

    if not analysis.success:
        report_section["status"] = "failed"
        report_section["analysis_status"] = "failed"
        report_section["error"] = analysis.error or "Grounded analysis failed"
        report_section["sandbox_analysis"] = {
            "success": False,
            "error": analysis.error,
        }
        return report_section

    report_section["sandbox_analysis"] = {
        "success": True,
        "execution_time_ms": analysis.execution_time_ms,
        "code_executed": analysis.code_executed,
    }
    report_section["computed_stats"] = analysis.computed_stats
    report_section["chart_manifest"] = analysis.chart_manifest
    report_section["chart_html"] = analysis.chart_html
    report_section["chart_image"] = {
        "image_data": analysis.image_data,
        "image_format": analysis.image_format,
    }
    report_section["analysis_status"] = "done"
    report_section["visualization"] = {
        "success": bool(analysis.image_data),
        "image_data": analysis.image_data,
        "image_format": analysis.image_format,
        "execution_time_ms": analysis.execution_time_ms,
        "error": analysis.error,
    }
    return report_section


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

    report_schema_context = _resolve_report_schema_context(state)
    worker_state = {
        **state,
        "report_schema_context": report_schema_context,
    }
    with ThreadPoolExecutor(max_workers=min(len(sections), 4)) as executor:
        completed_sections = list(executor.map(lambda section: _run_report_section(worker_state, section), sections))

    failed_sections = [section for section in completed_sections if section.get("status") == "failed"]
    return {
        "report_sections": completed_sections,
        "report_status": "insighting",
        "report_schema_context": report_schema_context,
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


def _build_report_insight_messages(
    state: AgentState,
    section: ReportSection,
) -> list[dict[str, Any]]:
    system_messages = prompt_manager.report_insight_system_messages()
    stats_json = json.dumps(section.get("computed_stats", {}), ensure_ascii=False, indent=2, default=str)
    manifest_json = json.dumps(section.get("chart_manifest", {}), ensure_ascii=False, indent=2, default=str)
    text_content = (
        f"Original report request:\n{state.get('report_request') or state.get('user_query', '')}\n\n"
        f"Section title:\n{section.get('title', '')}\n\n"
        f"Section analysis query:\n{section.get('analysis_query', '')}\n\n"
        f"computed_stats.json:\n{stats_json}\n\n"
        f"chart_manifest.json:\n{manifest_json}\n\n"
        "Return JSON only."
    )

    image = (section.get("chart_image") or {}).get("image_data")
    image_format = (section.get("chart_image") or {}).get("image_format", "png")
    if not image:
        return system_messages + [{"role": "user", "content": text_content}]

    data_url = (
        f"data:image/{image_format};base64,"
        f"{base64.b64encode(image).decode('utf-8')}"
    )
    return system_messages + [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": text_content},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    ]


def _fallback_section_insight(section: ReportSection) -> ReportSection:
    computed_stats = section.get("computed_stats") or {}
    row_count = computed_stats.get("row_count", section.get("sql_result", {}).get("row_count", 0))
    warnings = ((computed_stats.get("data_quality") or {}).get("warnings") if isinstance(computed_stats, dict) else None) or []
    limitations = [str(item) for item in warnings if str(item).strip()]
    insight = f"Dữ liệu cho mục này có {row_count} dòng. Các số liệu chi tiết được neo vào computed_stats.json."
    if limitations:
        insight += " " + " ".join(limitations)
    return {
        **section,
        "insight_markdown": insight,
        "insight_citations": [{"json_path": "row_count", "value": str(row_count)}],
        "limitations": limitations,
    }


def _generate_section_insight(state: AgentState, section: ReportSection) -> ReportSection:
    if section.get("status") == "failed" or section.get("analysis_status") != "done":
        error = section.get("error", "Unknown section failure")
        return {
            **section,
            "insight_markdown": f"Không thể tạo insight cho mục này: {error}",
            "insight_citations": [],
            "limitations": [str(error)],
        }

    settings = load_settings()
    messages = _build_report_insight_messages(state, section)
    try:
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=messages,
            model=settings.model_report_writer,
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
        insight_markdown = str(parsed.get("insight_markdown", "")).strip()
        citations = parsed.get("citations", [])
        limitations = parsed.get("limitations", [])
        if not insight_markdown:
            return _fallback_section_insight(section)
        return {
            **section,
            "insight_markdown": insight_markdown,
            "insight_citations": citations if isinstance(citations, list) else [],
            "limitations": limitations if isinstance(limitations, list) else [],
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Report insight generation failed: {error}", error=str(exc))
        return _fallback_section_insight(section)


def report_insight_generator_node(state: AgentState) -> AgentState:
    sections = state.get("report_sections", [])
    if not sections:
        return {
            "report_status": "failed",
            "errors": [
                {
                    "category": "REPORT_INSIGHT_ERROR",
                    "message": "No report sections available for insight generation.",
                }
            ],
        }

    with ThreadPoolExecutor(max_workers=min(len(sections), 4)) as executor:
        completed_sections = list(executor.map(lambda section: _generate_section_insight(state, section), sections))

    return {
        "report_sections": completed_sections,
        "report_status": "writing",
        "tool_history": [
            {
                "tool": "report_insight_generator",
                "status": "ok",
                "section_count": len(completed_sections),
            }
        ],
    }


def _section_writer_payload(section: ReportSection) -> dict[str, Any]:
    return {
        "section_id": section.get("section_id"),
        "title": section.get("title"),
        "analysis_query": section.get("analysis_query"),
        "status": section.get("status"),
        "insight_markdown": section.get("insight_markdown", ""),
        "limitations": section.get("limitations", []),
    }


def _section_critic_payload(section: ReportSection) -> dict[str, Any]:
    return {
        "section_id": section.get("section_id"),
        "title": section.get("title"),
        "status": section.get("status"),
        "insight_markdown": section.get("insight_markdown", ""),
        "citations": section.get("insight_citations", []),
        "computed_stats": section.get("computed_stats", {}),
        "limitations": section.get("limitations", []),
    }


def report_writer_node(state: AgentState) -> AgentState:
    settings = load_settings()
    report_plan = json.dumps(state.get("report_plan", {}), ensure_ascii=False, indent=2, default=str)
    section_results = json.dumps(
        [_section_writer_payload(section) for section in state.get("report_sections", [])],
        ensure_ascii=False,
        indent=2,
        default=str,
    )
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
            temperature=0.0,
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

    report_draft = _cleanup_report_markdown(report_draft)

    if not report_draft:
        lines = [f"# {state.get('report_plan', {}).get('title', 'Report')}"]
        for section in state.get("report_sections", []):
            lines.append(f"## {section.get('title', 'Section')}")
            if section.get("status") == "failed":
                lines.append(f"Mục này thất bại: {section.get('error', 'Unknown error')}")
            else:
                lines.append(section.get("insight_markdown", "Không có insight cho mục này."))
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
    section_results = json.dumps(
        [_section_critic_payload(section) for section in state.get("report_sections", [])],
        ensure_ascii=False,
        indent=2,
        default=str,
    )
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
    report_markdown = _cleanup_report_markdown(state.get("report_draft", ""))
    plan_title = state.get("report_plan", {}).get("title", "Report")
    errors = state.get("errors", [])
    answer = "Đây là report của bạn. Bấm vào nút Report để xem bản trình bày đầy đủ."
    payload = {
        "answer": answer,
        "report_markdown": report_markdown or f"# {plan_title}\n\nNo report content was generated.",
        "report_sections": [
            _report_section_payload(section)
            for section in state.get("report_sections", [])
            if section.get("status") == "done"
        ],
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
        "report_final": payload["report_markdown"],
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
    builder.add_node(
        "report_insight_generator",
        _instrument_node("report_insight_generator_node", report_insight_generator_node),
    )
    builder.add_node("report_writer", _instrument_node("report_writer_node", report_writer_node))
    builder.add_node("report_critic", _instrument_node("report_critic_node", report_critic_node))
    builder.add_node("report_finalize", _instrument_node("report_finalize_node", report_finalize_node))

    builder.add_edge(START, "report_planner")
    builder.add_edge("report_planner", "report_executor")
    builder.add_edge("report_executor", "report_insight_generator")
    builder.add_edge("report_insight_generator", "report_writer")
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
