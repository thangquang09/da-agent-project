from __future__ import annotations

import base64
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.config import load_settings
from app.graph.sql_worker_graph import get_sql_worker_graph
from app.graph.state import AgentState, ReportPlan, ReportSection, SectionPlan
from app.llm import LLMClient
from app.logger import logger
from app.observability import get_current_tracer
from app.prompts import prompt_manager
from app.tools.get_schema import get_schema_overview
from app.tools.query_sql import query_sql
from app.artifacts.helpers import (
    save_section_chart_to_file,
    save_report_markdown_to_file,
    read_chart_bytes,
    chart_url_from_path,
)
from app.graph.report_validators import run_report_validators
from app.tools.visualization import get_visualization_service

_ALLOWED_ANALYSIS_TYPES = {
    "descriptive",
    "comparative",
    "trend",
    "distribution",
    "composition",
    "correlation",
    "cohort",
    "funnel",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    # First try to extract from markdown code blocks
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    # Fallback: find first { ... } pair
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
    fenced = re.match(
        r"^```(?:markdown|md)?\s*([\s\S]*?)\s*```$", stripped, re.IGNORECASE
    )
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
                same_text = _normalize_heading_text(
                    previous_match.group(2)
                ) == _normalize_heading_text(heading_match.group(2))
                if same_text:
                    continue
        output.append(line)
    return "\n".join(output).strip()


def _truncate_json_for_prompt(data: dict[str, Any], max_chars: int = 8000) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    if len(text) <= max_chars:
        return text
    trimmed: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, list) and len(value) > 20:
            trimmed[key] = value[:20]
            trimmed[f"{key}_truncated"] = (
                f"... ({len(value)} total items, showing first 20)"
            )
        elif isinstance(value, dict):
            trimmed[key] = value
        else:
            trimmed[key] = value
    text = json.dumps(trimmed, ensure_ascii=False, indent=2, default=str)
    if len(text) > max_chars:
        return text[:max_chars] + "\n... (truncated)"
    return text


def _truncate_text(text: str, max_chars: int = 3000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... (truncated)"


def _normalize_analysis_type(value: Any, *, query: str = "", title: str = "") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _ALLOWED_ANALYSIS_TYPES:
        return normalized

    hint = f"{title} {query}".lower()
    if any(
        token in hint
        for token in ["trend", "over time", "theo thời gian", "month", "year"]
    ):
        return "trend"
    if any(token in hint for token in ["distribution", "phân phối", "histogram"]):
        return "distribution"
    if any(
        token in hint
        for token in ["compare", "comparison", "vs", "so sánh", "khác biệt"]
    ):
        return "comparative"
    if any(token in hint for token in ["share", "composition", "cơ cấu", "tỷ trọng"]):
        return "composition"
    if any(
        token in hint
        for token in ["correlation", "relationship", "liên hệ", "tương quan"]
    ):
        return "correlation"
    if any(token in hint for token in ["cohort"]):
        return "cohort"
    if any(token in hint for token in ["funnel"]):
        return "funnel"
    return "descriptive"


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _keyword_tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-zA-Z0-9_]+", (text or "").lower())
        if len(token) >= 3
    ]


def _question_id_list(
    questions: list[dict[str, Any]], *, priority: str | None = None
) -> list[str]:
    ids: list[str] = []
    for question in questions:
        if priority and str(question.get("priority", "must")) != priority:
            continue
        question_id = str(question.get("question_id", "")).strip()
        if question_id:
            ids.append(question_id)
    return ids


def _hypothesis_id_list(hypotheses: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for hypothesis in hypotheses:
        hypothesis_id = str(hypothesis.get("hypothesis_id", "")).strip()
        if hypothesis_id:
            ids.append(hypothesis_id)
    return ids


def _detect_output_language(text: str) -> str:
    return "vi" if _is_probably_vietnamese(text) else "en"


def _report_output_language(state: AgentState) -> str:
    language = (
        str((state.get("report_constraints") or {}).get("output_language", ""))
        .strip()
        .lower()
    )
    if language in {"vi", "en"}:
        return language
    source_text = (
        state.get("report_original_request")
        or state.get("report_request")
        or state.get("user_query", "")
    )
    return _detect_output_language(source_text)


def _is_vietnamese_output(state: AgentState) -> bool:
    return _report_output_language(state) == "vi"


def _report_heading(kind: str, *, is_vietnamese: bool) -> str:
    headings = {
        "executive_summary": (
            "## Tóm tắt điều hành" if is_vietnamese else "## Executive Summary"
        ),
        "follow_up": (
            "## Câu hỏi cần làm rõ thêm"
            if is_vietnamese
            else "## Questions Requiring Follow-up"
        ),
        "conclusion": "## Kết luận" if is_vietnamese else "## Conclusion",
        "recommendations": "## Khuyến nghị" if is_vietnamese else "## Recommendations",
    }
    return headings[kind]


def _has_recommendations_heading(text: str) -> bool:
    return bool(
        re.search(
            r"^##\s+(Recommendations|Khuyến nghị)\b",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )
    )


def _detect_requested_visualizations(text: str) -> bool:
    lowered = (text or "").lower()
    return any(
        token in lowered
        for token in [
            "biểu đồ",
            "chart",
            "charts",
            "visualization",
            "visualizations",
            "trực quan",
            "dashboard",
        ]
    )


def _detect_answer_style(text: str) -> str:
    lowered = (text or "").lower()
    if any(token in lowered for token in ["executive", "ban lãnh đạo", "lãnh đạo"]):
        return "executive"
    if any(
        token in lowered for token in ["technical", "kỹ thuật", "chi tiết kỹ thuật"]
    ):
        return "technical"
    return "analyst"


def _infer_question_intent_type(text: str) -> str:
    lowered = (text or "").lower()
    if any(token in lowered for token in ["trend", "theo thời gian", "over time"]):
        return "trend"
    if any(token in lowered for token in ["tại sao", "why", "nguyên nhân", "driver"]):
        return "diagnostic"
    if any(
        token in lowered
        for token in ["cao nhất", "thấp nhất", "highest", "lowest", "top"]
    ):
        return "ranking"
    if any(token in lowered for token in ["phân phối", "distribution", "histogram"]):
        return "distribution"
    if any(token in lowered for token in ["tương quan", "correlation", "liên hệ"]):
        return "correlation"
    if any(
        token in lowered
        for token in ["so sánh", "compare", "vs", "versus", "khác nhau"]
    ):
        return "comparison"
    return "descriptive"


def _infer_hypothesis_test_type(text: str) -> str:
    lowered = (text or "").lower()
    if any(token in lowered for token in ["tương quan", "correlation", "liên hệ"]):
        return "correlation"
    if any(token in lowered for token in ["trend", "theo thời gian", "over time"]):
        return "trend"
    if any(token in lowered for token in ["so sánh", "compare", "vs", "versus"]):
        return "compare"
    return "explore"


def _intent_to_analysis_type(intent_type: str) -> str:
    return {
        "comparison": "comparative",
        "ranking": "comparative",
        "trend": "trend",
        "distribution": "distribution",
        "correlation": "correlation",
    }.get(intent_type, "descriptive")


def _split_report_objective(text: str) -> tuple[str, str]:
    stripped = str(text or "").strip()
    patterns = [
        r"\btrả lời các câu hỏi\b",
        r"\btrả lời câu hỏi\b",
        r"\banswer these questions\b",
        r"\banswer the following questions\b",
        r"\banswer the question\b",
        r"\bquestions?\s*:\s*",
    ]
    for pattern in patterns:
        match = re.search(pattern, stripped, flags=re.IGNORECASE)
        if not match:
            continue
        objective = stripped[: match.start()].strip().rstrip(",;:-")
        tail = stripped[match.end() :].strip().lstrip(":-")
        return objective or stripped, tail
    return stripped, ""


def _fallback_question_texts(text: str) -> list[str]:
    _, tail = _split_report_objective(text)
    if not tail:
        return []

    tail = tail.replace("\n", " ").strip()
    parts = [
        part.strip(" ,;:-")
        for part in re.split(r"\s*(?:\?|;|,|\band\b|\bvà\b)\s*", tail)
        if part.strip(" ,;:-")
    ]
    questions: list[str] = []
    for part in parts:
        cleaned = part.strip()
        if not cleaned:
            continue
        if not cleaned.endswith("?"):
            cleaned = f"{cleaned}?"
        questions.append(cleaned)
    return questions


def _summarize_last_action(last_action: Any) -> str:
    if not isinstance(last_action, dict) or not last_action:
        return ""
    parts: list[str] = []
    for key in ("tool", "action", "query", "summary"):
        value = str(last_action.get(key, "")).strip()
        if value:
            parts.append(f"{key}={value}")
    return "; ".join(parts)[:400]


def _normalize_report_question(raw: Any, index: int) -> dict[str, Any]:
    if isinstance(raw, dict):
        text = str(raw.get("text", "")).strip()
        priority = str(raw.get("priority", "must") or "must").strip().lower()
        source = (
            str(raw.get("source", "current_query") or "current_query").strip().lower()
        )
        intent_type = str(raw.get("intent_type", "") or "").strip().lower()
    else:
        text = str(raw or "").strip()
        priority = "must"
        source = "current_query"
        intent_type = ""

    return {
        "question_id": str(
            raw.get("question_id", "") if isinstance(raw, dict) else ""
        ).strip()
        or f"q{index}",
        "text": text,
        "priority": priority if priority in {"must", "should"} else "must",
        "source": source if source in {"current_query", "session"} else "current_query",
        "intent_type": intent_type
        if intent_type
        in {
            "descriptive",
            "comparison",
            "trend",
            "diagnostic",
            "ranking",
            "distribution",
            "correlation",
        }
        else _infer_question_intent_type(text),
        "entities": _as_string_list(raw.get("entities"))
        if isinstance(raw, dict)
        else [],
        "time_scope": str(raw.get("time_scope")).strip()
        if isinstance(raw, dict) and raw.get("time_scope")
        else None,
        "requested_metrics": _as_string_list(raw.get("requested_metrics"))
        if isinstance(raw, dict)
        else [],
        "requested_dimensions": _as_string_list(raw.get("requested_dimensions"))
        if isinstance(raw, dict)
        else [],
    }


def _normalize_report_hypothesis(raw: Any, index: int) -> dict[str, Any]:
    if isinstance(raw, dict):
        text = str(raw.get("text", "")).strip()
        priority = str(raw.get("priority", "should") or "should").strip().lower()
        source = (
            str(raw.get("source", "current_query") or "current_query").strip().lower()
        )
        test_type = str(raw.get("test_type", "") or "").strip().lower()
    else:
        text = str(raw or "").strip()
        priority = "should"
        source = "current_query"
        test_type = ""

    return {
        "hypothesis_id": str(
            raw.get("hypothesis_id", "") if isinstance(raw, dict) else ""
        ).strip()
        or f"h{index}",
        "text": text,
        "priority": priority if priority in {"must", "should"} else "should",
        "source": source if source in {"current_query", "session"} else "current_query",
        "test_type": test_type
        if test_type in {"compare", "trend", "correlation", "explore"}
        else _infer_hypothesis_test_type(text),
        "entities": _as_string_list(raw.get("entities"))
        if isinstance(raw, dict)
        else [],
    }


def _normalize_report_constraints(raw: Any, original_request: str) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    answer_style = str(data.get("answer_style", "") or "").strip().lower()
    return {
        "output_language": str(data.get("output_language", "") or "").strip()
        or _detect_output_language(original_request),
        "requested_visualizations": bool(
            data.get("requested_visualizations")
            if "requested_visualizations" in data
            else _detect_requested_visualizations(original_request)
        ),
        "requested_sections": _as_string_list(data.get("requested_sections")),
        "excluded_topics": _as_string_list(data.get("excluded_topics")),
        "time_scope": str(data.get("time_scope")).strip()
        if data.get("time_scope")
        else None,
        "answer_style": answer_style
        if answer_style in {"analyst", "executive", "technical"}
        else _detect_answer_style(original_request),
    }


def _build_report_followup_context(
    state: AgentState, followup_notes: str = ""
) -> dict[str, Any]:
    task_profile = state.get("task_profile") or {}
    followup_mode = str(
        task_profile.get("followup_mode", "fresh_query") or "fresh_query"
    )
    session_context_summary = str(followup_notes or "").strip()
    if not session_context_summary:
        session_context_summary = _truncate_text(state.get("session_context", ""), 500)
    return {
        "followup_mode": followup_mode
        if followup_mode in {"fresh_query", "followup", "refine_previous_result"}
        else "fresh_query",
        "session_context_summary": session_context_summary,
        "last_action_summary": _summarize_last_action(state.get("last_action")),
        "conversation_turn": int(state.get("conversation_turn", 0) or 0),
    }


def _build_report_planning_brief(
    state: AgentState,
    *,
    domain_context: str = "",
    answerable_question_ids: list[str] | None = None,
    risky_question_ids: list[str] | None = None,
    unanswerable_question_ids: list[str] | None = None,
    hypothesis_assessment: list[dict[str, Any]] | None = None,
    planning_risks: list[str] | None = None,
    suggested_analytical_directions: list[str] | None = None,
) -> dict[str, Any]:
    existing_brief = state.get("report_planning_brief") or {}
    return {
        "original_request": state.get("report_original_request")
        or state.get("report_request")
        or state.get("user_query", ""),
        "objective": state.get("report_user_objective")
        or state.get("report_request")
        or state.get("user_query", ""),
        "user_questions": state.get("report_user_questions") or [],
        "user_hypotheses": state.get("report_user_hypotheses") or [],
        "constraints": state.get("report_constraints") or {},
        "followup_context": state.get("report_followup_context") or {},
        "answerable_question_ids": answerable_question_ids
        if answerable_question_ids is not None
        else existing_brief.get("answerable_question_ids", []),
        "risky_question_ids": risky_question_ids
        if risky_question_ids is not None
        else existing_brief.get("risky_question_ids", []),
        "unanswerable_question_ids": unanswerable_question_ids
        if unanswerable_question_ids is not None
        else existing_brief.get("unanswerable_question_ids", []),
        "hypothesis_assessment": hypothesis_assessment
        if hypothesis_assessment is not None
        else existing_brief.get("hypothesis_assessment", []),
        "domain_context": domain_context or existing_brief.get("domain_context", ""),
        "planning_risks": planning_risks
        if planning_risks is not None
        else existing_brief.get("planning_risks", []),
        "suggested_analytical_directions": suggested_analytical_directions
        if suggested_analytical_directions is not None
        else existing_brief.get("suggested_analytical_directions", []),
    }


def _normalize_subset_ids(raw: Any, valid_ids: set[str]) -> list[str]:
    normalized: list[str] = []
    for item in _as_string_list(raw):
        if item in valid_ids and item not in normalized:
            normalized.append(item)
    return normalized


def _normalize_hypothesis_assessment(
    raw_items: Any,
    hypothesis_ids: set[str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not isinstance(raw_items, list):
        return items
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        hypothesis_id = str(raw.get("hypothesis_id", "")).strip()
        if hypothesis_id not in hypothesis_ids:
            continue
        status = str(raw.get("status", "risky") or "risky").strip().lower()
        if status not in {"answerable", "risky", "untestable"}:
            status = "risky"
        item = {
            "hypothesis_id": hypothesis_id,
            "status": status,
        }
        reason = str(raw.get("reason", "")).strip()
        if reason:
            item["reason"] = reason
        items.append(item)
    return items


def _build_report_sample_summary(sample_data: dict[str, Any]) -> str:
    sample_summary_parts: list[str] = []
    for table_name, table_info in sample_data.items():
        if not isinstance(table_info, dict) or "error" in table_info:
            continue
        rows = table_info.get("sample_rows", [])
        col_stats = table_info.get("column_stats", [])
        row_preview = json.dumps(rows[:10], ensure_ascii=False, default=str)
        if len(row_preview) > 2000:
            row_preview = row_preview[:2000] + "..."
        stats_text = json.dumps(col_stats, ensure_ascii=False, default=str)
        if len(stats_text) > 1500:
            stats_text = stats_text[:1500] + "..."
        sample_summary_parts.append(
            f"### Table: {table_name}\n"
            f"Estimated total rows: {table_info.get('table_row_count', table_info.get('sample_count', 0))}\n"
            f"Total sample rows: {table_info.get('sample_count', 0)}\n"
            f"Columns: {', '.join(table_info.get('columns', []))}\n"
            f"Column stats:\n{stats_text}\n"
            f"Sample rows (first 10):\n{row_preview}"
        )
    return (
        "\n\n".join(sample_summary_parts)
        if sample_summary_parts
        else "(no sample data available)"
    )


def _fallback_dataset_profile(state: AgentState) -> dict[str, Any]:
    sample_data = state.get("report_sample_data") or {}
    sampled_tables = [
        table_name
        for table_name, table_info in sample_data.items()
        if isinstance(table_info, dict) and not table_info.get("error")
    ]
    table_profiles: list[dict[str, Any]] = []
    for table_name in sampled_tables:
        table_info = sample_data.get(table_name) or {}
        table_profiles.append(
            {
                "table_name": table_name,
                "row_estimate": table_info.get(
                    "table_row_count", table_info.get("sample_count", 0)
                ),
                "sample_row_count": table_info.get("sample_count", 0),
                "columns": table_info.get("columns", []),
                "likely_metrics": [],
                "likely_dimensions": [],
                "time_columns": [],
                "notes": "Fallback profile derived from sampled rows and schema only.",
            }
        )

    profiling_risks = [
        f"Sampling failed for table '{table_name}': {table_info.get('error')}"
        for table_name, table_info in sample_data.items()
        if isinstance(table_info, dict) and table_info.get("error")
    ]
    if not sampled_tables:
        profiling_risks.append(
            "No tables were successfully sampled, so answerability assessment may be unreliable."
        )

    dataset_summary = ""
    if sampled_tables:
        dataset_summary = f"The available dataset currently centers on {', '.join(sampled_tables[:3])}."

    return {
        "candidate_tables": sampled_tables,
        "selected_tables": sampled_tables,
        "table_profiles": table_profiles,
        "join_hints": [],
        "profiling_risks": profiling_risks,
        "dataset_summary": dataset_summary,
        "key_metrics": [],
        "key_dimensions": [],
        "analytical_angles": [],
    }


def _normalize_dataset_profile(raw: Any, state: AgentState) -> dict[str, Any]:
    fallback = _fallback_dataset_profile(state)
    data = raw if isinstance(raw, dict) else {}
    sample_data = state.get("report_sample_data") or {}
    known_tables = set(sample_data) | set(fallback.get("candidate_tables", []))

    candidate_tables = [
        table_name
        for table_name in _as_string_list(data.get("candidate_tables"))
        if table_name in known_tables or not known_tables
    ]
    if not candidate_tables:
        candidate_tables = fallback.get("candidate_tables", [])

    selected_tables = [
        table_name
        for table_name in _as_string_list(data.get("selected_tables"))
        if table_name in candidate_tables or not candidate_tables
    ]
    if not selected_tables:
        selected_tables = candidate_tables or fallback.get("selected_tables", [])

    raw_profiles = (
        data.get("table_profiles")
        if isinstance(data.get("table_profiles"), list)
        else []
    )
    profile_lookup: dict[str, dict[str, Any]] = {}
    for raw_profile in raw_profiles:
        if not isinstance(raw_profile, dict):
            continue
        table_name = str(
            raw_profile.get("table_name") or raw_profile.get("name") or ""
        ).strip()
        if table_name:
            profile_lookup[table_name] = raw_profile

    table_profiles: list[dict[str, Any]] = []
    for table_name in selected_tables:
        sample_info = (
            sample_data.get(table_name) if isinstance(sample_data, dict) else {}
        )
        raw_profile = profile_lookup.get(table_name, {})
        table_profiles.append(
            {
                "table_name": table_name,
                "row_estimate": raw_profile.get(
                    "row_estimate",
                    sample_info.get(
                        "table_row_count", sample_info.get("sample_count", 0)
                    )
                    if isinstance(sample_info, dict)
                    else 0,
                ),
                "sample_row_count": raw_profile.get(
                    "sample_row_count",
                    sample_info.get("sample_count", 0)
                    if isinstance(sample_info, dict)
                    else 0,
                ),
                "columns": _as_string_list(raw_profile.get("columns"))
                or (
                    sample_info.get("columns", [])
                    if isinstance(sample_info, dict)
                    else []
                ),
                "likely_metrics": _as_string_list(raw_profile.get("likely_metrics")),
                "likely_dimensions": _as_string_list(
                    raw_profile.get("likely_dimensions")
                ),
                "time_columns": _as_string_list(raw_profile.get("time_columns")),
                "notes": str(raw_profile.get("notes", "")).strip(),
            }
        )

    if not table_profiles:
        table_profiles = fallback.get("table_profiles", [])

    join_hints = [
        raw_hint
        for raw_hint in (data.get("join_hints") or [])
        if isinstance(raw_hint, dict)
    ]
    profiling_risks = _as_string_list(data.get("profiling_risks")) or fallback.get(
        "profiling_risks", []
    )

    return {
        "candidate_tables": candidate_tables,
        "selected_tables": selected_tables,
        "table_profiles": table_profiles,
        "join_hints": join_hints,
        "profiling_risks": profiling_risks,
        "dataset_summary": str(data.get("dataset_summary", "")).strip()
        or fallback.get("dataset_summary", ""),
        "key_metrics": _as_string_list(data.get("key_metrics")),
        "key_dimensions": _as_string_list(data.get("key_dimensions")),
        "analytical_angles": _as_string_list(data.get("analytical_angles")),
    }


def _fallback_brief_builder_output(state: AgentState) -> dict[str, Any]:
    questions = state.get("report_user_questions") or []
    question_ids = _question_id_list(questions)
    dataset_profile = state.get("dataset_profile") or {}
    selected_tables = _as_string_list(dataset_profile.get("selected_tables"))
    profiling_risks = _as_string_list(dataset_profile.get("profiling_risks"))

    if selected_tables:
        answerable_question_ids = question_ids
        risky_question_ids: list[str] = []
        unanswerable_question_ids: list[str] = []
    else:
        answerable_question_ids = []
        risky_question_ids = []
        unanswerable_question_ids = question_ids
        profiling_risks.append(
            "No tables were confidently selected for the report brief, so explicit questions remain unresolved."
        )

    hypothesis_assessment = []
    for hypothesis_id in _hypothesis_id_list(state.get("report_user_hypotheses") or []):
        hypothesis_assessment.append(
            {
                "hypothesis_id": hypothesis_id,
                "status": "answerable" if selected_tables else "untestable",
                "reason": "Fallback assessment based on whether any tables were selected for profiling.",
            }
        )

    return {
        "answerable_question_ids": answerable_question_ids,
        "risky_question_ids": risky_question_ids,
        "unanswerable_question_ids": unanswerable_question_ids,
        "hypothesis_assessment": hypothesis_assessment,
        "domain_context": str(dataset_profile.get("dataset_summary", "")).strip(),
        "planning_risks": profiling_risks,
        "suggested_analytical_directions": _as_string_list(
            dataset_profile.get("analytical_angles")
        ),
    }


def _normalize_report_brief_output(raw: Any, state: AgentState) -> dict[str, Any]:
    fallback = _fallback_brief_builder_output(state)
    data = raw if isinstance(raw, dict) else {}
    has_model_output = bool(data)
    question_ids = set(_question_id_list(state.get("report_user_questions") or []))
    must_question_ids = set(
        _question_id_list(state.get("report_user_questions") or [], priority="must")
    )
    hypothesis_ids = set(_hypothesis_id_list(state.get("report_user_hypotheses") or []))

    answerable_question_ids = _normalize_subset_ids(
        data.get("answerable_question_ids"), question_ids
    )
    risky_question_ids = [
        question_id
        for question_id in _normalize_subset_ids(
            data.get("risky_question_ids"), question_ids
        )
        if question_id not in answerable_question_ids
    ]
    unanswerable_question_ids = [
        question_id
        for question_id in _normalize_subset_ids(
            data.get("unanswerable_question_ids"), question_ids
        )
        if question_id not in answerable_question_ids
        and question_id not in risky_question_ids
    ]

    assigned_ids = (
        set(answerable_question_ids)
        | set(risky_question_ids)
        | set(unanswerable_question_ids)
    )
    selected_tables = _as_string_list(
        (state.get("dataset_profile") or {}).get("selected_tables")
    )
    for question_id in must_question_ids - assigned_ids:
        if selected_tables:
            risky_question_ids.append(question_id)
        else:
            unanswerable_question_ids.append(question_id)

    return {
        "answerable_question_ids": answerable_question_ids
        if has_model_output
        else fallback.get("answerable_question_ids", []),
        "risky_question_ids": risky_question_ids
        if has_model_output
        else fallback.get("risky_question_ids", []),
        "unanswerable_question_ids": unanswerable_question_ids
        if has_model_output
        else fallback.get("unanswerable_question_ids", []),
        "hypothesis_assessment": _normalize_hypothesis_assessment(
            data.get("hypothesis_assessment"), hypothesis_ids
        )
        or fallback.get("hypothesis_assessment", []),
        "domain_context": str(data.get("domain_context", "")).strip()
        or fallback.get("domain_context", ""),
        "planning_risks": _as_string_list(data.get("planning_risks"))
        or fallback.get("planning_risks", []),
        "suggested_analytical_directions": _as_string_list(
            data.get("suggested_analytical_directions")
        )
        or fallback.get("suggested_analytical_directions", []),
    }


def _report_domain_context(state: AgentState) -> str:
    planning_brief = state.get("report_planning_brief") or {}
    dataset_profile = state.get("dataset_profile") or {}
    legacy_profile = state.get("report_data_profile") or {}
    return str(
        planning_brief.get("domain_context")
        or dataset_profile.get("dataset_summary")
        or legacy_profile.get("dataset_summary")
        or legacy_profile.get("domain_summary")
        or ""
    ).strip()


def _fallback_report_request_grounding(
    original_request: str,
    state: AgentState,
) -> dict[str, Any]:
    objective, _ = _split_report_objective(original_request)
    questions = [
        {
            "text": question,
            "priority": "must",
            "intent_type": _infer_question_intent_type(question),
            "entities": [],
            "time_scope": None,
            "requested_metrics": [],
            "requested_dimensions": [],
        }
        for question in _fallback_question_texts(original_request)
    ]
    return {
        "objective": objective or original_request,
        "questions": questions,
        "hypotheses": [],
        "constraints": {
            "output_language": _detect_output_language(original_request),
            "requested_visualizations": _detect_requested_visualizations(
                original_request
            ),
            "requested_sections": [],
            "excluded_topics": [],
            "time_scope": None,
            "answer_style": _detect_answer_style(original_request),
        },
        "followup_notes": "",
    }


def _planner_sample_summary(sample_data: dict[str, Any]) -> str:
    lines: list[str] = []
    for table_name, table_info in sample_data.items():
        if not isinstance(table_info, dict) or table_info.get("error"):
            continue
        columns = ", ".join(table_info.get("columns", [])[:10])
        lines.append(
            f"- {table_name}: rows~{table_info.get('table_row_count', table_info.get('sample_count', 0))}, columns=[{columns}]"
        )
    return "\n".join(lines)


def _normalize_unresolved_items(raw_items: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not isinstance(raw_items, list):
        return items
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        item_type = str(raw.get("item_type", "question") or "question").strip().lower()
        item: dict[str, Any] = {
            "item_type": item_type
            if item_type in {"question", "hypothesis"}
            else "question",
            "reason": str(raw.get("reason", "")).strip(),
        }
        question_id = str(raw.get("question_id", "")).strip()
        hypothesis_id = str(raw.get("hypothesis_id", "")).strip()
        if question_id:
            item["question_id"] = question_id
        if hypothesis_id:
            item["hypothesis_id"] = hypothesis_id
        if item.get("reason"):
            items.append(item)
    return items


def _build_fallback_question_section(
    question: dict[str, Any],
    *,
    order: int,
    requested_visualizations: bool,
) -> dict[str, Any]:
    question_text = str(question.get("text", "")).strip()
    intent_type = str(question.get("intent_type", "descriptive") or "descriptive")
    analysis_type = _intent_to_analysis_type(intent_type)
    return {
        "section_id": f"question-{question.get('question_id', order)}",
        "title": question_text[:80] or f"Question {order}",
        "business_question": question_text,
        "analysis_query": question_text,
        "analysis_type": analysis_type,
        "target_metrics": question.get("requested_metrics", []),
        "target_dimensions": question.get("requested_dimensions", []),
        "expected_grain": "dataset",
        "confidence_notes": "Deterministic fallback section added to preserve must-answer coverage.",
        "requires_visualization": requested_visualizations
        or analysis_type in {"comparative", "trend", "distribution", "composition"},
        "section_order": order,
        "inclusion_reason": "Added automatically because the planner output did not map a must-answer user question.",
        "addresses_question_ids": [question.get("question_id")],
        "tests_hypothesis_ids": [],
        "must_include": True,
        "status": "pending",
    }


def _build_fallback_report_plan(query: str, state: AgentState) -> dict[str, Any]:
    questions = state.get("report_user_questions") or []
    constraints = state.get("report_constraints") or {}
    sections: list[dict[str, Any]] = []
    for index, question in enumerate(questions, start=1):
        sections.append(
            _build_fallback_question_section(
                question,
                order=index,
                requested_visualizations=bool(
                    constraints.get("requested_visualizations", False)
                ),
            )
        )

    if not sections:
        sections = [
            {
                "section_id": "1",
                "title": "Overview",
                "business_question": query,
                "analysis_query": query,
                "analysis_type": "descriptive",
                "target_metrics": [],
                "target_dimensions": [],
                "expected_grain": "dataset",
                "confidence_notes": "Fallback plan due to missing planner output.",
                "requires_visualization": bool(
                    constraints.get("requested_visualizations", False)
                ),
                "section_order": 1,
                "inclusion_reason": "Fallback overview section.",
                "addresses_question_ids": [],
                "tests_hypothesis_ids": [],
                "must_include": True,
                "status": "pending",
            }
        ]

    return {
        "title": f"Report: {query[:80]}".strip(),
        "executive_summary_instruction": "Summarize the most important findings from the available data.",
        "sections": sections,
        "conclusion_instruction": "Conclude with grounded findings and limitations.",
        "coverage_summary": {
            "covered_question_ids": [],
            "unanswered_question_ids": _question_id_list(questions, priority="must"),
        },
        "unresolved_items": [],
    }


def _select_tables_for_report(
    all_tables: list[str],
    *,
    query: str,
    table_contexts: dict[str, str],
    limit: int = 2,
) -> list[str]:
    if not all_tables:
        return []

    query_tokens = Counter(_keyword_tokens(query))
    ranked: list[tuple[int, int, str]] = []
    for index, table in enumerate(all_tables):
        table_text = f"{table} {table_contexts.get(table, '')}"
        table_tokens = set(_keyword_tokens(table_text))
        overlap_score = sum(query_tokens.get(token, 0) for token in table_tokens)
        context_bonus = 3 if table_contexts.get(table) else 0
        exact_bonus = 5 if table.lower() in (query or "").lower() else 0
        ranked.append((overlap_score + context_bonus + exact_bonus, -index, table))

    ranked.sort(reverse=True)
    selected = [table for score, _, table in ranked if score > 0][:limit]
    if len(selected) < limit:
        for table in all_tables:
            if table not in selected:
                selected.append(table)
            if len(selected) >= limit:
                break
    return selected[:limit]


def _build_table_profile_query(table: str, columns: list[str]) -> str:
    select_parts = ['COUNT(*) AS "__total_rows"']
    for col in columns:
        select_parts.extend(
            [
                f'COUNT(DISTINCT "{col}") AS "__distinct__{col}"',
                f'SUM(CASE WHEN "{col}" IS NULL THEN 1 ELSE 0 END) AS "__nulls__{col}"',
            ]
        )
    return f'SELECT {", ".join(select_parts)} FROM "{table}"'


def _extract_column_stats(
    stats_row: dict[str, Any],
    columns: list[str],
) -> tuple[int, list[dict[str, Any]]]:
    total_rows = int(stats_row.get("__total_rows", 0) or 0)
    column_stats: list[dict[str, Any]] = []
    for col in columns:
        column_stats.append(
            {
                "column": col,
                "total_rows": total_rows,
                "distinct_count": int(stats_row.get(f"__distinct__{col}", 0) or 0),
                "null_count": int(stats_row.get(f"__nulls__{col}", 0) or 0),
            }
        )
    return total_rows, column_stats


def _first_nonempty_paragraph(text: str) -> str:
    for block in re.split(r"\n\s*\n", text or ""):
        cleaned = block.strip()
        if cleaned:
            return cleaned
    return ""


def _is_probably_vietnamese(text: str) -> bool:
    lowered = (text or "").lower()
    return bool(
        re.search(
            r"[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]",
            lowered,
        )
    )


def _build_cautious_recommendations(state: AgentState) -> list[str]:
    is_vietnamese = _is_vietnamese_output(state)
    recommendations: list[str] = []
    if any(
        section.get("semantic_warnings") for section in state.get("report_sections", [])
    ):
        recommendations.append(
            "Xác minh lại metric definition, grain phân tích, và cách tính các tỷ lệ trước khi dùng report này cho quyết định quan trọng."
            if is_vietnamese
            else "Verify metric definitions, analysis grain, and any rate calculations before using this report for important decisions."
        )
    if any(
        section.get("section_confidence") == "low"
        for section in state.get("report_sections", [])
    ):
        recommendations.append(
            "Ưu tiên kiểm tra thêm các section có confidence thấp bằng truy vấn sâu hơn hoặc phân tích thủ công trước khi diễn giải mạnh."
            if is_vietnamese
            else "Investigate low-confidence sections further with deeper queries or manual analysis before making strong interpretations."
        )
    recommendations.append(
        "Dùng report này như bước mô tả và định hướng điều tra tiếp theo, không coi là bằng chứng nhân quả hay khuyến nghị can thiệp cuối cùng."
        if is_vietnamese
        else "Use this report as descriptive guidance for further investigation, not as causal proof or a final intervention recommendation."
    )
    return recommendations[:3]


def _ensure_report_recommendations(text: str, state: AgentState) -> str:
    if _has_recommendations_heading(text):
        return text
    recommendations = _build_cautious_recommendations(state)
    if not recommendations:
        return text
    lines = [
        text.rstrip(),
        "",
        _report_heading("recommendations", is_vietnamese=_is_vietnamese_output(state)),
        "",
    ]
    for index, recommendation in enumerate(recommendations, start=1):
        lines.append(f"{index}. {recommendation}")
    return "\n".join(lines).strip()


def _humanize_semantic_warning(warning: str, *, is_vietnamese: bool) -> str:
    lowered = warning.lower()
    if "average-of-averages" in lowered or "avg(" in lowered:
        return (
            "cách tính tỷ lệ có thể đang dùng trung bình-của-trung-bình và cần xác minh lại"
            if is_vietnamese
            else "the rate calculation may rely on an average-of-averages and should be verified"
        )
    if "correlation-style" in lowered or "causal" in lowered:
        return (
            "phân tích này chỉ mang tính mô tả tương quan, chưa đủ để diễn giải nhân quả"
            if is_vietnamese
            else "this analysis is descriptive and should not be interpreted causally"
        )
    if "very small result set" in lowered or "small result set" in lowered:
        return (
            "cỡ mẫu của section này nhỏ nên chênh lệch quan sát được có thể kém ổn định"
            if is_vietnamese
            else "the section is based on a small result set, so observed differences may be unstable"
        )
    cleaned = warning.strip().rstrip(".")
    return cleaned if not is_vietnamese else cleaned.lower()


def _build_safe_report_markdown(state: AgentState) -> str:
    original_request = (
        state.get("report_original_request")
        or state.get("report_request")
        or state.get("user_query", "")
    )
    is_vietnamese = _is_vietnamese_output(state)
    plan_title = state.get("report_plan", {}).get("title", "Report")
    sections = [
        section
        for section in state.get("report_sections", [])
        if section.get("status") == "done"
    ]
    summary_heading = _report_heading("executive_summary", is_vietnamese=is_vietnamese)
    unresolved_heading = _report_heading("follow_up", is_vietnamese=is_vietnamese)
    conclusion_heading = _report_heading("conclusion", is_vietnamese=is_vietnamese)
    lines = [f"# {plan_title}", "", summary_heading, ""]

    summary = (
        "Báo cáo dưới đây chỉ tổng hợp các phát hiện đã được grounding ở từng mục. Một số phần diễn giải mức cao đã bị lược bỏ vì bản nháp tường thuật đầy đủ không sẵn có hoặc chưa vượt qua bước phản biện."
        if is_vietnamese
        else "This report only summarizes findings that were grounded in section-level evidence. Higher-level interpretation was reduced because the full narrative draft was unavailable or did not pass review."
    )
    first_section_paragraph = ""
    if sections:
        first_section_paragraph = _first_nonempty_paragraph(
            sections[0].get("insight_markdown", "")
        )
    lines.append(first_section_paragraph or summary)

    for section in sections:
        lines.extend(
            [
                "",
                f"## {section.get('title', 'Section')}",
                "",
                section.get(
                    "insight_markdown", "Không có insight cho mục này."
                ).strip(),
            ]
        )

    unresolved_items = state.get("report_unresolved_items") or []
    question_lookup = {
        question.get("question_id"): question.get("text", "")
        for question in state.get("report_user_questions", [])
        if question.get("question_id")
    }
    if unresolved_items:
        lines.extend(["", unresolved_heading, ""])
        for item in unresolved_items:
            question_text = question_lookup.get(item.get("question_id", ""), "")
            reason = str(item.get("reason", "")).strip()
            if question_text:
                lines.append(f"- {question_text}: {reason}")
            elif reason:
                lines.append(f"- {reason}")

    all_limitations = [
        limitation.strip()
        for section in sections
        for limitation in section.get("limitations", [])
        if limitation and limitation.strip()
    ]
    lines.extend(["", conclusion_heading, ""])
    lines.append(
        "Các kết luận dưới đây chỉ nên được hiểu là phần tổng hợp an toàn từ những mục đã có evidence trực tiếp."
        if is_vietnamese
        else "The conclusions below should be read as a conservative synthesis of sections with direct supporting evidence."
    )
    if all_limitations:
        lines.append(
            "Các hạn chế dữ liệu và phạm vi phân tích đã được ghi rõ trong từng mục tương ứng, và cần được xem xét trước khi đưa ra quyết định."
            if is_vietnamese
            else "Data limitations and analysis scope constraints are noted in the relevant sections and should be reviewed before acting on this report."
        )

    recommendations: list[str] = []
    if all_limitations:
        recommendations.append(
            "Rà soát kỹ các hạn chế dữ liệu đã được nêu trong từng mục trước khi chuyển các phát hiện này thành quyết định vận hành."
            if is_vietnamese
            else "Review the section-level data limitations carefully before turning these findings into operational decisions."
        )
    if sections:
        recommendations.append(
            "Đối chiếu lại các phát hiện quan trọng nhất với metric definition, grain phân tích, và câu hỏi kinh doanh gốc trước khi hành động."
            if is_vietnamese
            else "Cross-check the most important findings against metric definitions, analysis grain, and the original business questions before acting."
        )
    recommendations.append(
        "Nếu cần quyết định có tác động lớn, hãy chạy thêm phân tích chuyên sâu hoặc kiểm định bổ sung thay vì chỉ dựa vào bản tóm tắt an toàn này."
        if is_vietnamese
        else "For high-impact decisions, run deeper analysis or additional validation instead of relying only on this conservative summary."
    )

    lines.extend(
        [
            "",
            _report_heading("recommendations", is_vietnamese=is_vietnamese),
            "",
        ]
    )
    for index, recommendation in enumerate(recommendations[:4], start=1):
        lines.append(f"**{index}. {recommendation}**")
        lines.append("")

    return _cleanup_report_markdown("\n".join(lines))


def _report_section_payload(section: ReportSection) -> dict[str, Any]:
    chart_image_url = section.get("chart_image_url")
    chart_image_format = section.get("chart_image_format", "png")
    visualization = section.get("visualization") or {}
    return {
        "section_id": section.get("section_id", ""),
        "title": section.get("title", ""),
        "business_question": section.get("business_question", ""),
        "insight_markdown": section.get("insight_markdown", ""),
        "chart_image": (
            {
                "success": bool(chart_image_url),
                "image_url": chart_image_url,
                "image_format": chart_image_format,
                "image_size_bytes": visualization.get("image_size_bytes", 0),
                "execution_time_ms": visualization.get("execution_time_ms", 0.0),
                "error": visualization.get("error"),
            }
            if chart_image_url
            else None
        ),
        "chart_manifest": section.get("chart_manifest"),
        "evidence_packets": section.get("evidence_packets", []),
        "claims": section.get("claims", []),
        "limitations": section.get("limitations", []),
        "analysis_type": section.get("analysis_type", "descriptive"),
        "addresses_question_ids": section.get("addresses_question_ids", []),
        "tests_hypothesis_ids": section.get("tests_hypothesis_ids", []),
        "semantic_warnings": section.get("semantic_warnings", []),
        "section_confidence": section.get("section_confidence", "medium"),
    }


def _writer_stats_payload(section: ReportSection) -> dict[str, Any] | None:
    computed_stats = section.get("computed_stats") or {}
    if not isinstance(computed_stats, dict):
        return None

    payload: dict[str, Any] = {
        "row_count": computed_stats.get("row_count"),
        "metrics": computed_stats.get("metrics", {}),
        "comparisons": computed_stats.get("comparisons", {}),
        "rankings": computed_stats.get("rankings", {}),
        "data_quality": computed_stats.get("data_quality", {}),
    }
    grouped_rows = computed_stats.get("grouped_rows")
    if isinstance(grouped_rows, list) and grouped_rows:
        payload["grouped_rows"] = grouped_rows[:5]
        payload["row_bindings"] = computed_stats.get("row_bindings", {})
    if section.get("semantic_warnings"):
        payload["semantic_warnings"] = section.get("semantic_warnings", [])
    if section.get("section_confidence"):
        payload["section_confidence"] = section.get("section_confidence")
    return payload


def _collect_metric_like_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = str(key).lower()
            if any(
                token in lowered for token in ["rate", "ratio", "pct", "percent", "%"]
            ):
                keys.add(lowered)
            keys.update(_collect_metric_like_keys(nested))
    elif isinstance(value, list):
        for item in value:
            keys.update(_collect_metric_like_keys(item))
    return keys


def _validate_section_semantics(section: ReportSection) -> ReportSection:
    warnings: list[str] = []
    computed_stats = section.get("computed_stats") or {}
    if not isinstance(computed_stats, dict):
        computed_stats = {}

    analysis_type = _normalize_analysis_type(
        section.get("analysis_type"),
        query=section.get("analysis_query", ""),
        title=section.get("title", ""),
    )
    query = str(section.get("analysis_query", ""))
    validated_sql = str(
        section.get("validated_sql") or section.get("generated_sql", "")
    )
    row_count = int(
        computed_stats.get("row_count")
        or section.get("sql_result", {}).get("row_count", 0)
        or 0
    )
    underlying_observation_count = _underlying_observation_count(
        _load_report_rows(section), computed_stats
    )
    grouped_rows = (
        computed_stats.get("grouped_rows")
        if isinstance(computed_stats.get("grouped_rows"), list)
        else []
    )
    data_quality = (
        computed_stats.get("data_quality")
        if isinstance(computed_stats.get("data_quality"), dict)
        else {}
    )
    chart_manifest = (
        section.get("chart_manifest")
        if isinstance(section.get("chart_manifest"), dict)
        else {}
    )
    series = (
        computed_stats.get("series")
        if isinstance(computed_stats.get("series"), list)
        else []
    )

    for warning in data_quality.get("warnings", []):
        warning_text = str(warning).strip()
        if warning_text:
            warnings.append(warning_text)

    if row_count == 0:
        warnings.append(
            "Section returned no rows, so no analytical conclusion should be treated as reliable."
        )
    elif underlying_observation_count is not None and underlying_observation_count < 5:
        warnings.append(
            "Section is based on a very small result set; treat differences and recommendations cautiously."
        )

    if analysis_type == "comparative" and len(grouped_rows) < 2:
        warnings.append(
            "Comparative section does not expose at least two grounded groups, so comparisons may be incomplete."
        )
    if analysis_type == "trend" and not series:
        warnings.append(
            "Trend section lacks an explicit grounded time series, so trend wording should stay conservative."
        )
    if analysis_type == "distribution" and not computed_stats.get("metrics"):
        warnings.append(
            "Distribution section is missing summary metrics, so distributional interpretation is limited."
        )
    if analysis_type == "correlation":
        warnings.append(
            "Correlation-style sections remain descriptive here and should not be interpreted as causal evidence."
        )

    lowered_query = query.lower()
    if any(
        token in lowered_query for token in ["rate", "ratio", "%", "percent", "tỷ lệ"]
    ):
        if re.search(r"\bavg\s*\(", validated_sql, flags=re.IGNORECASE):
            warnings.append(
                "This section appears to use AVG(...) for a rate/ratio-style question; verify that the aggregation is not an average-of-averages mistake."
            )

    if validated_sql.lower().count(" join ") >= 2 and re.search(
        r"\b(group by|sum\s*\(|avg\s*\(|count\s*\()", validated_sql, flags=re.IGNORECASE
    ):
        warnings.append(
            "The SQL uses multiple joins with aggregation; verify the intended grain to avoid duplicated-row inflation."
        )

    metric_like_keys = _collect_metric_like_keys(computed_stats)
    if metric_like_keys:
        for key in metric_like_keys:
            if "pct" in key or "percent" in key or "%" in key:
                continue
            # ratio/rate usually expected in [0,1] unless explicitly marked percent
            for row in grouped_rows[:20]:
                if isinstance(row, dict) and key in {
                    str(k).lower() for k in row.keys()
                }:
                    for k, v in row.items():
                        if (
                            str(k).lower() == key
                            and isinstance(v, (int, float))
                            and v > 1
                        ):
                            warnings.append(
                                f"Metric '{k}' exceeds 1.0; confirm whether it is a proportion or should be expressed as a percentage/count instead."
                            )
                            break

    if chart_manifest.get("chart_type") == "table" and analysis_type in {
        "comparative",
        "trend",
        "distribution",
        "composition",
    }:
        warnings.append(
            "Section fell back to a table-style artifact, so visual evidence may be weaker than the analysis type suggests."
        )

    deduped_warnings = _dedupe_quality_warnings(warnings)

    if row_count == 0:
        semantic_status = "failed"
        section_confidence = "low"
    elif len(deduped_warnings) >= 3:
        semantic_status = "warning"
        section_confidence = "low"
    elif deduped_warnings:
        semantic_status = "warning"
        section_confidence = "medium"
    else:
        semantic_status = "ok"
        section_confidence = "high"

    return {
        **section,
        "analysis_type": analysis_type,
        "semantic_warnings": deduped_warnings,
        "semantic_status": semantic_status,
        "section_confidence": section_confidence,
    }


def _derive_report_confidence(
    state: AgentState, *, used_safe_fallback: bool
) -> tuple[str, str]:
    failed_sections = sum(
        1
        for section in state.get("report_sections", [])
        if section.get("status") == "failed"
    )
    total_limitations = sum(
        len(section.get("limitations", []))
        for section in state.get("report_sections", [])
        if isinstance(section.get("limitations"), list)
    )
    low_confidence_sections = sum(
        1
        for section in state.get("report_sections", [])
        if section.get("section_confidence") == "low"
    )
    semantic_warning_count = sum(
        len(section.get("semantic_warnings", []))
        for section in state.get("report_sections", [])
        if isinstance(section.get("semantic_warnings"), list)
    )
    critic_issues = [
        str(issue).strip()
        for issue in state.get("critic_issues", [])
        if str(issue).strip()
    ]

    reasons: list[str] = []
    confidence = "high"
    if used_safe_fallback:
        confidence = "low"
        reasons.append(
            "Writer draft did not pass the critic, so the final report was reduced to a conservative extractive fallback."
        )
    elif (
        failed_sections > 0
        or critic_issues
        or low_confidence_sections > 0
        or semantic_warning_count > 0
    ):
        confidence = "medium"

    if failed_sections > 0:
        reasons.append(f"{failed_sections} section(s) failed during report generation.")
    if critic_issues:
        reasons.append(
            f"Critic flagged {len(critic_issues)} issue(s) that weaken confidence in the synthesized narrative."
        )
    if total_limitations > 0:
        reasons.append(
            f"The completed sections reported {total_limitations} limitation note(s) that narrow the safe interpretation scope."
        )
    if low_confidence_sections > 0:
        reasons.append(
            f"{low_confidence_sections} section(s) were marked low-confidence by semantic validation."
        )
    if semantic_warning_count > 0:
        reasons.append(
            f"Semantic validation emitted {semantic_warning_count} warning(s) about aggregation, grain, or evidence quality."
        )
    unresolved_items = len(state.get("report_unresolved_items") or [])
    if unresolved_items > 0:
        reasons.append(
            f"{unresolved_items} required user ask(s) remained unresolved and were carried forward with explicit caveats."
        )

    if not reasons:
        reasons.append(
            "All completed sections were grounded and the draft passed the critic without flagged issues."
        )
    return confidence, " ".join(reasons)


def _default_report_plan(query: str) -> ReportPlan:
    return _build_fallback_report_plan(query, {})


# ---------------------------------------------------------------------------
# NODE 1: Request Grounder — preserve explicit asks before planning
# ---------------------------------------------------------------------------


def report_request_grounder_node(state: AgentState) -> AgentState:
    original_request = (
        state.get("report_request") or state.get("user_query", "")
    ).strip()
    serialized_last_action = json.dumps(
        state.get("last_action") or {}, ensure_ascii=False, indent=2, default=str
    )
    serialized_task_profile = json.dumps(
        state.get("task_profile") or {}, ensure_ascii=False, indent=2, default=str
    )

    grounded: dict[str, Any] = {}
    try:
        settings = load_settings()
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=prompt_manager.report_request_grounder_messages(
                report_original_request=original_request,
                session_context=state.get("session_context", ""),
                last_action=serialized_last_action,
                task_profile=serialized_task_profile,
            ),
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
        grounded = _extract_first_json_object(content) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("report_request_grounder failed: {error}", error=str(exc))

    if not grounded:
        grounded = _fallback_report_request_grounding(original_request, state)

    objective = str(grounded.get("objective", "")).strip() or original_request
    raw_questions = grounded.get("questions") or []
    raw_hypotheses = grounded.get("hypotheses") or []
    normalized_questions: list[dict[str, Any]] = []
    for index, raw_question in enumerate(raw_questions, start=1):
        question = _normalize_report_question(raw_question, index)
        if question.get("text"):
            normalized_questions.append(question)

    normalized_hypotheses: list[dict[str, Any]] = []
    for index, raw_hypothesis in enumerate(raw_hypotheses, start=1):
        hypothesis = _normalize_report_hypothesis(raw_hypothesis, index)
        if hypothesis.get("text"):
            normalized_hypotheses.append(hypothesis)
    constraints = _normalize_report_constraints(
        grounded.get("constraints"),
        original_request,
    )
    followup_context = _build_report_followup_context(
        state,
        followup_notes=str(grounded.get("followup_notes", "")).strip(),
    )
    update: AgentState = {
        "report_request": original_request,
        "report_original_request": original_request,
        "report_user_objective": objective,
        "report_user_questions": normalized_questions,
        "report_user_hypotheses": normalized_hypotheses,
        "report_constraints": constraints,
        "report_followup_context": followup_context,
        "report_planning_brief": {
            "original_request": original_request,
            "objective": objective,
            "user_questions": normalized_questions,
            "user_hypotheses": normalized_hypotheses,
            "constraints": constraints,
            "followup_context": followup_context,
            "answerable_question_ids": [],
            "risky_question_ids": [],
            "unanswerable_question_ids": [],
            "hypothesis_assessment": [],
            "domain_context": "",
            "planning_risks": [],
            "suggested_analytical_directions": [],
        },
        "tool_history": [
            {
                "tool": "report_request_grounder",
                "status": "ok",
                "question_count": len(normalized_questions),
                "hypothesis_count": len(normalized_hypotheses),
            }
        ],
    }
    return update


# ---------------------------------------------------------------------------
# NODE 2: Profiler Sampler — runs SQL to fetch 100 random rows + column stats
# ---------------------------------------------------------------------------


# Tables that are system/utility tables and should be excluded from profiling
_SYSTEM_TABLES = frozenset(
    {
        "result_store",
        "trace_store",
        "conversation_history",
        "data_summaries",
        "artifact_store",
        "schema_migrations",
    }
)


def _extract_tables_from_xml(xml_context: str) -> list[str]:
    """Extract table names from XML database context, excluding system tables."""
    # Match <table name="xxx"> or <table_name>xxx</table_name> patterns
    names = re.findall(r'<table\s+name="([^"]+)"', xml_context)
    if not names:
        names = re.findall(r"<table_name>([^<]+)</table_name>", xml_context)
    # Filter out system tables and cap at 3 user tables
    return [n for n in names if n.lower() not in _SYSTEM_TABLES][:3]


def profiler_sampler_node(state: AgentState) -> AgentState:
    """Run SQL queries to fetch 100 random sample rows and column statistics
    for each relevant table. This gives the analyzer LLM actual data to reason about."""
    xml_ctx = state.get("xml_database_context", "")
    all_tables = _extract_tables_from_xml(xml_ctx)
    query = (
        state.get("report_original_request")
        or state.get("report_request")
        or state.get("user_query", "")
    )
    db_path_raw = state.get("target_db_path", "")
    db_path = Path(db_path_raw) if db_path_raw else None

    table_contexts = state.get("table_contexts") or {}
    tables = _select_tables_for_report(
        all_tables,
        query=query,
        table_contexts=table_contexts,
        limit=2,
    )

    if not tables:
        logger.warning("profiler_sampler: no tables found in xml_database_context")
        return {
            "report_sample_data": {},
            "tool_history": [{"tool": "profiler_sampler", "status": "no_tables"}],
        }

    logger.info(
        "profiler_sampler: sampling {n} tables: {tables}",
        n=len(tables),
        tables=tables,
    )

    sample_data: dict[str, Any] = {}
    for table in tables:
        try:
            # Keep row sampling cheap; quality comes from combining this with whole-table stats.
            sample_sql = f'SELECT * FROM "{table}" LIMIT 100'
            sample_result = query_sql(sample_sql, db_path=db_path)
            sample_rows = sample_result.get("rows", [])
            columns = sample_result.get("columns", [])[:15]

            total_rows = len(sample_rows)
            col_stats: list[dict[str, Any]] = []
            if columns:
                try:
                    stats_sql = _build_table_profile_query(table, columns)
                    stats_result = query_sql(stats_sql, db_path=db_path)
                    row = (stats_result.get("rows") or [{}])[0]
                    total_rows, col_stats = _extract_column_stats(row, columns)
                except Exception:  # noqa: BLE001
                    col_stats = [
                        {"column": col, "error": "stats query failed"}
                        for col in columns
                    ]

            sample_data[table] = {
                "sample_rows": sample_rows[:100],
                "sample_count": len(sample_rows),
                "table_row_count": total_rows,
                "columns": columns,
                "column_stats": col_stats,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "profiler_sampler: failed to sample table {table}: {error}",
                table=table,
                error=str(exc),
            )
            sample_data[table] = {"error": str(exc)}

    return {
        "report_sample_data": sample_data,
        "tool_history": [
            {
                "tool": "profiler_sampler",
                "status": "ok",
                "tables_sampled": len(sample_data),
            }
        ],
    }


# ---------------------------------------------------------------------------
# NODE 3: Dataset Profiler — LLM reads schema + sample data → dataset affordances
# ---------------------------------------------------------------------------


def report_dataset_profiler_node(state: AgentState) -> AgentState:
    """LLM-based profiler: reads schema + sample data and returns dataset affordances only."""
    query = (
        state.get("report_original_request")
        or state.get("report_request")
        or state.get("user_query", "")
    )
    sample_data = state.get("report_sample_data") or {}
    sample_summary = _build_report_sample_summary(sample_data)

    table_contexts = state.get("table_contexts") or {}
    business_context_parts = [
        f"Table '{t}': {ctx}" for t, ctx in table_contexts.items() if ctx
    ]
    business_context = (
        "\n".join(business_context_parts) if business_context_parts else ""
    )

    messages = prompt_manager.report_data_profiler_messages(
        query=query,
        xml_database_context=state.get("xml_database_context", ""),
        sample_data_summary=sample_summary,
        business_context=business_context,
    )
    try:
        settings = load_settings()
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=messages,
            model=settings.model_report_data_profiler,
            temperature=0.0,
            stream=False,
        )
        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        logger.info(
            "report_dataset_profiler: LLM response length={len}, preview={preview}",
            len=len(content),
            preview=content[:300].replace("{", "(").replace("}", ")"),
        )
        dataset_profile = _normalize_dataset_profile(
            _extract_first_json_object(content) or {},
            state,
        )
        logger.info(
            "report_dataset_profiler: selected_tables={tables}, risks={n}",
            tables=dataset_profile.get("selected_tables", []),
            n=len(dataset_profile.get("profiling_risks", [])),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Report data profiler failed: {error}", error=str(exc))
        dataset_profile = _fallback_dataset_profile(state)

    return {
        "dataset_profile": dataset_profile,
        "report_data_profile": dataset_profile,
        "tool_history": [
            {
                "tool": "report_dataset_profiler",
                "status": "ok" if dataset_profile else "fallback",
                "selected_tables": dataset_profile.get("selected_tables", []),
            }
        ],
    }


profiler_analyzer_node = report_dataset_profiler_node


# ---------------------------------------------------------------------------
# NODE 4: Brief Builder — reconcile user asks with dataset affordances
# ---------------------------------------------------------------------------


def report_brief_builder_node(state: AgentState) -> AgentState:
    query = (
        state.get("report_original_request")
        or state.get("report_request")
        or state.get("user_query", "")
    )
    dataset_profile = (
        state.get("dataset_profile") or state.get("report_data_profile") or {}
    )
    sample_summary = _build_report_sample_summary(state.get("report_sample_data") or {})
    raw_output: dict[str, Any] = {}

    try:
        settings = load_settings()
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=prompt_manager.report_brief_builder_messages(
                report_original_request=query,
                report_user_objective=state.get("report_user_objective", ""),
                report_user_questions=_truncate_json_for_prompt(
                    {"questions": state.get("report_user_questions", [])},
                    6000,
                ),
                report_user_hypotheses=_truncate_json_for_prompt(
                    {"hypotheses": state.get("report_user_hypotheses", [])},
                    4000,
                ),
                report_constraints=_truncate_json_for_prompt(
                    state.get("report_constraints") or {},
                    2000,
                ),
                report_followup_context=_truncate_json_for_prompt(
                    state.get("report_followup_context") or {},
                    2000,
                ),
                dataset_profile=_truncate_json_for_prompt(dataset_profile, 10000),
                table_contexts=_truncate_json_for_prompt(
                    {"table_contexts": state.get("table_contexts") or {}},
                    4000,
                ),
                sample_data_summary=sample_summary,
            ),
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
        raw_output = _extract_first_json_object(content) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Report brief builder failed: {error}", error=str(exc))

    normalized = _normalize_report_brief_output(raw_output, state)
    planning_brief = _build_report_planning_brief(
        state,
        domain_context=normalized.get("domain_context", ""),
        answerable_question_ids=normalized.get("answerable_question_ids", []),
        risky_question_ids=normalized.get("risky_question_ids", []),
        unanswerable_question_ids=normalized.get("unanswerable_question_ids", []),
        hypothesis_assessment=normalized.get("hypothesis_assessment", []),
        planning_risks=normalized.get("planning_risks", []),
        suggested_analytical_directions=normalized.get(
            "suggested_analytical_directions", []
        ),
    )

    return {
        "report_planning_brief": planning_brief,
        "tool_history": [
            {
                "tool": "report_brief_builder",
                "status": "ok",
                "answerable_question_count": len(
                    planning_brief.get("answerable_question_ids", [])
                ),
                "unanswerable_question_count": len(
                    planning_brief.get("unanswerable_question_ids", [])
                ),
            }
        ],
    }


# ---------------------------------------------------------------------------
# NODE 5: Planner — produces _report_sections_planned for Send()
# ---------------------------------------------------------------------------


def _normalize_planner_section(
    raw: Any,
    *,
    index: int,
    question_ids: set[str],
    hypothesis_ids: set[str],
) -> SectionPlan | None:
    if not isinstance(raw, dict):
        return None
    analysis_query = str(
        raw.get("analysis_query") or raw.get("business_question") or ""
    ).strip()
    if not analysis_query:
        return None

    title = str(raw.get("title", "")).strip() or f"Section {index}"
    return {
        "section_id": str(raw.get("section_id", "")).strip() or f"sec-{index}",
        "title": title,
        "business_question": str(raw.get("business_question", "")).strip()
        or analysis_query,
        "analysis_query": analysis_query,
        "analysis_type": _normalize_analysis_type(
            raw.get("analysis_type"),
            query=analysis_query,
            title=title,
        ),
        "target_metrics": _as_string_list(raw.get("target_metrics")),
        "target_dimensions": _as_string_list(raw.get("target_dimensions")),
        "expected_grain": str(raw.get("expected_grain", "dataset")).strip()
        or "dataset",
        "confidence_notes": str(raw.get("confidence_notes", "")).strip(),
        "requires_visualization": bool(raw.get("requires_visualization", False)),
        "section_order": index,
        "inclusion_reason": str(raw.get("inclusion_reason", "")).strip()
        or "Planner-selected section.",
        "addresses_question_ids": [
            question_id
            for question_id in _as_string_list(raw.get("addresses_question_ids"))
            if question_id in question_ids
        ],
        "tests_hypothesis_ids": [
            hypothesis_id
            for hypothesis_id in _as_string_list(raw.get("tests_hypothesis_ids"))
            if hypothesis_id in hypothesis_ids
        ],
        "must_include": bool(
            raw.get("must_include", _as_string_list(raw.get("addresses_question_ids")))
        ),
        "status": "pending",
    }


def report_planner_node(state: AgentState) -> AgentState:
    query = (
        state.get("report_original_request")
        or state.get("report_request")
        or state.get("user_query", "")
    )
    settings = load_settings()

    dataset_profile = (
        state.get("dataset_profile") or state.get("report_data_profile") or {}
    )
    planning_brief = state.get("report_planning_brief") or _build_report_planning_brief(
        state
    )
    domain_context = str(
        planning_brief.get("domain_context")
        or dataset_profile.get("dataset_summary")
        or ""
    ).strip()
    report_questions = state.get("report_user_questions") or []
    report_hypotheses = state.get("report_user_hypotheses") or []
    question_ids = set(_question_id_list(report_questions))
    must_question_ids = _question_id_list(report_questions, priority="must")
    hypothesis_ids = set(_hypothesis_id_list(report_hypotheses))
    planning_risks = _as_string_list(
        planning_brief.get("planning_risks")
    ) or _as_string_list(dataset_profile.get("profiling_risks"))
    dataset_guidance = {
        "selected_tables": dataset_profile.get("selected_tables", []),
        "table_profiles": dataset_profile.get("table_profiles", []),
        "join_hints": dataset_profile.get("join_hints", []),
        "profiling_risks": dataset_profile.get("profiling_risks", []),
        "dataset_summary": dataset_profile.get("dataset_summary", ""),
        "key_metrics": dataset_profile.get("key_metrics", []),
        "key_dimensions": dataset_profile.get("key_dimensions", []),
        "analytical_angles": planning_brief.get("suggested_analytical_directions", [])
        or dataset_profile.get("analytical_angles", []),
    }

    logger.info(
        "report_planner: dataset_profile_keys={keys}, grounded_questions={q}, domain_context={ctx}",
        keys=list(dataset_profile.keys()),
        q=len(report_questions),
        ctx=domain_context[:100] if domain_context else "(empty)",
    )

    parsed_plan: dict[str, Any] = {}
    try:
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=prompt_manager.report_planner_messages(
                query=query,
                planning_brief=_truncate_json_for_prompt(planning_brief, 10000),
                xml_database_context=state.get("xml_database_context", ""),
                dataset_profile=_truncate_json_for_prompt(dataset_guidance, 8000),
                sample_data_summary=_planner_sample_summary(
                    state.get("report_sample_data") or {}
                ),
            ),
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
        parsed_plan = _extract_first_json_object(content) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Report planner failed: {error}", error=str(exc))

    plan = (
        parsed_plan
        if isinstance(parsed_plan.get("sections"), list)
        else _build_fallback_report_plan(query, state)
    )
    sections: list[SectionPlan] = []
    for idx, raw in enumerate(plan.get("sections", []), start=1):
        section = _normalize_planner_section(
            raw,
            index=idx,
            question_ids=question_ids,
            hypothesis_ids=hypothesis_ids,
        )
        if section:
            sections.append(section)

    if not sections:
        fallback_plan = _build_fallback_report_plan(query, state)
        sections = [
            section
            for idx, raw in enumerate(fallback_plan.get("sections", []), start=1)
            if (
                section := _normalize_planner_section(
                    raw,
                    index=idx,
                    question_ids=question_ids,
                    hypothesis_ids=hypothesis_ids,
                )
            )
        ]
        plan = fallback_plan

    unresolved_items = _normalize_unresolved_items(plan.get("unresolved_items"))
    unresolved_question_ids = {
        item.get("question_id")
        for item in unresolved_items
        if item.get("item_type") == "question" and item.get("question_id")
    }
    requested_visualizations = bool(
        (state.get("report_constraints") or {}).get("requested_visualizations", False)
    )
    question_lookup = {
        question.get("question_id"): question
        for question in report_questions
        if question.get("question_id")
    }
    for question_id in _as_string_list(planning_brief.get("unanswerable_question_ids")):
        if question_id in unresolved_question_ids or question_id not in question_lookup:
            continue
        unresolved_items.append(
            {
                "item_type": "question",
                "question_id": question_id,
                "reason": "The current dataset profile indicates this user question is not answerable with the available sampled data.",
            }
        )
        unresolved_question_ids.add(question_id)

    question_to_section_ids: dict[str, list[str]] = {}
    for section in sections:
        for question_id in section.get("addresses_question_ids", []):
            question_to_section_ids.setdefault(question_id, []).append(
                section.get("section_id", "")
            )

    updated_planning_risks = list(planning_risks)
    next_order = len(sections) + 1
    for question_id in must_question_ids:
        if (
            question_id in question_to_section_ids
            or question_id in unresolved_question_ids
        ):
            continue
        question = question_lookup.get(question_id)
        if not question:
            continue
        fallback_section = _build_fallback_question_section(
            question,
            order=next_order,
            requested_visualizations=requested_visualizations,
        )
        sections.append(fallback_section)
        question_to_section_ids.setdefault(question_id, []).append(
            fallback_section["section_id"]
        )
        updated_planning_risks.append(
            f"Planner output omitted must-answer question {question_id}; added deterministic fallback section."
        )
        next_order += 1

    covered_question_ids = sorted(question_to_section_ids)
    unresolved_question_ids_sorted = sorted(unresolved_question_ids)
    dropped_must_question_ids = [
        question_id
        for question_id in must_question_ids
        if question_id not in question_to_section_ids
        and question_id not in unresolved_question_ids
    ]
    coverage_summary = {
        "must_question_ids": must_question_ids,
        "covered_question_ids": covered_question_ids,
        "unresolved_question_ids": unresolved_question_ids_sorted,
        "dropped_must_question_ids": dropped_must_question_ids,
        "question_to_section_ids": question_to_section_ids,
    }

    plan["title"] = str(plan.get("title", "")).strip() or f"Report: {query[:80]}"
    plan["executive_summary_instruction"] = (
        str(plan.get("executive_summary_instruction", "")).strip()
        or "Summarize the most important grounded findings."
    )
    plan["conclusion_instruction"] = (
        str(plan.get("conclusion_instruction", "")).strip()
        or "Conclude with grounded findings, limitations, and cautious recommendations."
    )
    plan["sections"] = sections
    plan["coverage_summary"] = coverage_summary
    plan["unresolved_items"] = unresolved_items
    if domain_context:
        plan["domain_context"] = domain_context

    planning_brief = _build_report_planning_brief(
        state,
        domain_context=domain_context,
        answerable_question_ids=planning_brief.get("answerable_question_ids", []),
        risky_question_ids=planning_brief.get("risky_question_ids", []),
        unanswerable_question_ids=planning_brief.get("unanswerable_question_ids", []),
        hypothesis_assessment=planning_brief.get("hypothesis_assessment", []),
        planning_risks=updated_planning_risks,
        suggested_analytical_directions=planning_brief.get(
            "suggested_analytical_directions", []
        ),
    )

    return {
        "report_plan": plan,
        "_report_sections_planned": sections,
        "report_planning_brief": planning_brief,
        "report_question_coverage": coverage_summary,
        "report_unresolved_items": unresolved_items,
        "report_status": "executing",
        "tool_history": [
            {
                "tool": "report_planner",
                "status": "ok",
                "section_count": len(sections),
                "must_question_count": len(must_question_ids),
                "unresolved_count": len(unresolved_items),
            }
        ],
    }


# ---------------------------------------------------------------------------
# Send() fan-out: dispatches each section as a separate Send()
# ---------------------------------------------------------------------------


def fan_out_sections(state: AgentState) -> list[Send]:
    """Conditional edge that emits one Send() per planned section."""
    planned = state.get("_report_sections_planned") or []
    report_schema_context = _resolve_report_schema_context(state)
    sends = []
    for section in planned:
        sends.append(
            Send(
                "section_pipeline",
                {
                    **state,
                    "_current_section": section,
                    "report_schema_context": report_schema_context,
                },
            )
        )
    return sends


# ---------------------------------------------------------------------------
# NODE 6: Section Pipeline — per-section: SQL → sandbox → insight
# ---------------------------------------------------------------------------


def _load_report_rows(section_result: dict[str, Any]) -> list[dict[str, Any]]:
    sql_result = section_result.get("sql_result", {})
    result_ref = section_result.get("result_ref") or {}
    full_data_path = result_ref.get("full_data_path")
    if full_data_path:
        try:
            return json.loads(Path(full_data_path).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to load report rows from result_ref: {error}", error=str(exc)
            )
    rows = sql_result.get("rows", [])
    if isinstance(rows, list):
        return rows
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
        logger.warning(
            "Failed to resolve report schema context: {error}", error=str(exc)
        )
        return ""


def _build_report_insight_messages(
    state: AgentState,
    section: ReportSection,
) -> list[dict[str, Any]]:
    system_messages = prompt_manager.report_insight_system_messages()
    prompt_stats = _stats_payload_for_insight_prompt(section)
    stats_json = _truncate_json_for_prompt(prompt_stats, max_chars=6000)
    manifest_json = _truncate_json_for_prompt(
        section.get("chart_manifest", {}), max_chars=2000
    )
    domain_ctx = _report_domain_context(state)
    text_content = (
        f"Original report request:\n{state.get('report_original_request') or state.get('report_request') or state.get('user_query', '')}\n\n"
        f"Section title:\n{section.get('title', '')}\n\n"
        f"Section analysis query:\n{section.get('analysis_query', '')}\n\n"
        f"Section analysis type:\n{section.get('analysis_type', 'descriptive')}\n\n"
        f"Target metrics:\n{json.dumps(section.get('target_metrics', []), ensure_ascii=False)}\n\n"
        f"Target dimensions:\n{json.dumps(section.get('target_dimensions', []), ensure_ascii=False)}\n\n"
        f"Expected grain:\n{section.get('expected_grain', 'dataset')}\n\n"
        f"computed_stats.json:\n{stats_json}\n\n"
        f"chart_manifest.json:\n{manifest_json}\n\n"
        f"semantic_warnings:\n{json.dumps(section.get('semantic_warnings', []), ensure_ascii=False)}\n\n"
        f"Return JSON only."
    )
    if domain_ctx:
        text_content = f"Domain context: {domain_ctx}\n\n" + text_content

    chart_image_url = section.get("chart_image_url")
    image_format = section.get("chart_image_format", "png")
    if not chart_image_url:
        return system_messages + [{"role": "user", "content": text_content}]

    # Read image bytes from file for LLM multimodal input
    image = read_chart_bytes(
        chart_image_url
        if not chart_image_url.startswith("/artifacts/")
        else chart_image_url.lstrip("/artifacts/")
    )
    if not image:
        return system_messages + [{"role": "user", "content": text_content}]

    data_url = (
        f"data:image/{image_format};base64,{base64.b64encode(image).decode('utf-8')}"
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


def _stats_payload_for_insight_prompt(section: ReportSection) -> dict[str, Any]:
    computed_stats = section.get("computed_stats") or {}
    if not isinstance(computed_stats, dict):
        return {}

    grouped_rows = computed_stats.get("grouped_rows")
    if not isinstance(grouped_rows, list) or not grouped_rows:
        return computed_stats

    return {
        "section_title": computed_stats.get("section_title"),
        "query": computed_stats.get("query"),
        "row_count": computed_stats.get("row_count"),
        "row_bindings": computed_stats.get("row_bindings", {}),
        "grouped_rows": grouped_rows[:20],
        "data_quality": computed_stats.get("data_quality", {}),
    }


def _fallback_section_insight(section: ReportSection) -> ReportSection:
    computed_stats = section.get("computed_stats") or {}
    row_count = computed_stats.get(
        "row_count", section.get("sql_result", {}).get("row_count", 0)
    )
    warnings = (
        (computed_stats.get("data_quality") or {}).get("warnings")
        if isinstance(computed_stats, dict)
        else None
    ) or []
    limitations = [str(item) for item in warnings if str(item).strip()]
    semantic_warnings = [
        str(item).strip()
        for item in section.get("semantic_warnings", [])
        if str(item).strip()
    ]
    for warning in semantic_warnings:
        if warning not in limitations:
            limitations.append(warning)
    insight = (
        f"Dữ liệu cho mục này có {row_count} dòng. "
        f"Các số liệu chi tiết được neo vào computed_stats.json."
    )
    if limitations:
        insight += " " + " ".join(limitations)
    return {
        **section,
        "insight_markdown": insight,
        "insight_citations": [{"json_path": "row_count", "value": str(row_count)}],
        "limitations": limitations,
    }


def _apply_semantic_caveat(section: ReportSection, state: AgentState) -> ReportSection:
    warnings = [
        str(item).strip()
        for item in section.get("semantic_warnings", [])
        if str(item).strip()
    ]
    if not warnings:
        return section

    limitations = [
        str(item).strip()
        for item in section.get("limitations", [])
        if str(item).strip()
    ]
    for warning in warnings:
        if warning not in limitations:
            limitations.append(warning)

    insight_markdown = str(section.get("insight_markdown", "")).strip()
    is_vietnamese = _is_vietnamese_output(state)
    lower_insight = insight_markdown.lower()
    has_caveat_language = any(
        token in lower_insight
        for token in [
            "caveat",
            "thận trọng",
            "cần xác minh",
            "giới hạn",
            "không chứng minh",
            "descriptive",
        ]
    )
    if not has_caveat_language:
        warning_excerpt = _humanize_semantic_warning(
            warnings[0], is_vietnamese=is_vietnamese
        )
        if is_vietnamese:
            caveat_sentence = f"Lưu ý: phát hiện này nên được diễn giải thận trọng vì {warning_excerpt}."
        else:
            caveat_sentence = (
                f"Caveat: interpret this finding cautiously because {warning_excerpt}."
            )
        insight_markdown = f"{insight_markdown}\n\n{caveat_sentence}".strip()

    return {
        **section,
        "insight_markdown": insight_markdown,
        "limitations": limitations,
    }


def _analysis_type_to_request_type(analysis_type: str) -> str:
    return {
        "comparative": "comparison",
        "trend": "trend",
        "distribution": "breakdown",
        "composition": "breakdown",
        "correlation": "comparison",
        "cohort": "comparison",
        "funnel": "breakdown",
    }.get(analysis_type, "metric")


def _build_evidence_request(section: SectionPlan) -> dict[str, Any]:
    return {
        "request_id": f"{section.get('section_id', 'sec')}-req-1",
        "section_id": section.get("section_id", ""),
        "purpose": section.get("business_question") or section.get("title", ""),
        "request_type": _analysis_type_to_request_type(
            _normalize_analysis_type(
                section.get("analysis_type"),
                query=section.get("analysis_query", ""),
                title=section.get("title", ""),
            )
        ),
        "metric_specs": [
            {"name": metric}
            for metric in section.get("target_metrics", [])
            if str(metric).strip()
        ],
        "dimension_specs": [
            {"name": dimension}
            for dimension in section.get("target_dimensions", [])
            if str(dimension).strip()
        ],
        "filter_specs": [],
        "expected_grain": section.get("expected_grain", "dataset"),
        "analysis_query": section.get("analysis_query", ""),
    }


def _base_report_section(section: SectionPlan, result: dict[str, Any]) -> ReportSection:
    return {
        "section_id": section.get("section_id", "?"),
        "title": section.get("title", "Section"),
        "plan": section,
        "business_question": section.get("business_question", ""),
        "analysis_query": section.get("analysis_query", ""),
        "analysis_type": _normalize_analysis_type(
            section.get("analysis_type"),
            query=section.get("analysis_query", ""),
            title=section.get("title", ""),
        ),
        "target_metrics": section.get("target_metrics", []),
        "target_dimensions": section.get("target_dimensions", []),
        "expected_grain": section.get("expected_grain", "dataset"),
        "confidence_notes": section.get("confidence_notes", ""),
        "requires_visualization": bool(section.get("requires_visualization", True)),
        "section_order": section.get("section_order", 0),
        "inclusion_reason": section.get("inclusion_reason", ""),
        "addresses_question_ids": section.get("addresses_question_ids", []),
        "tests_hypothesis_ids": section.get("tests_hypothesis_ids", []),
        "must_include": bool(section.get("must_include", False)),
        "sql_result": result.get("sql_result", {}),
        "result_ref": result.get("result_ref"),
        "raw_result_ref": result.get("result_ref"),
        "evidence_requests": [],
        "evidence_packets": [],
        "claims": [],
        "visualization": None,
        "sandbox_analysis": None,
        "computed_stats": None,
        "chart_image_url": None,
        "chart_image_format": None,
        "chart_html": None,
        "chart_manifest": None,
        "narrative": "",
        "insight_markdown": "",
        "insight_citations": [],
        "limitations": [],
        "validation": {},
        "semantic_warnings": [],
        "semantic_status": "ok",
        "section_confidence": "high",
        "analysis_status": "failed" if result.get("status") != "success" else "pending",
        "status": "done" if result.get("status") == "success" else "failed",
        "error": result.get("error"),
        "generated_sql": result.get("generated_sql", ""),
        "validated_sql": result.get("validated_sql", ""),
    }


def _underlying_observation_count(
    rows: list[dict[str, Any]], computed_stats: dict[str, Any]
) -> int | None:
    explicit = computed_stats.get("underlying_observation_count")
    if isinstance(explicit, int):
        return explicit
    candidate_keys = {
        "count",
        "total",
        "total_count",
        "passenger_count",
        "student_count",
        "total_passengers",
        "observations",
        "n",
    }
    grouped_rows = computed_stats.get("grouped_rows")
    if isinstance(grouped_rows, list) and grouped_rows:
        totals: list[int] = []
        for row in grouped_rows[:50]:
            if not isinstance(row, dict):
                continue
            for key, value in row.items():
                lowered = str(key).lower()
                if lowered in candidate_keys and isinstance(value, (int, float)):
                    totals.append(int(value))
                    break
        if totals:
            return sum(totals)
    return len(rows) if rows else None


def _dedupe_quality_warnings(warnings: list[str]) -> list[str]:
    deduped: list[str] = []
    normalized_seen: set[str] = set()
    for warning in warnings:
        normalized = re.sub(r"\s+", " ", warning.strip().lower())
        normalized = normalized.replace("kích thước mẫu nhỏ", "small sample")
        normalized = normalized.replace("cỡ mẫu nhỏ", "small sample")
        if not normalized or normalized in normalized_seen:
            continue
        normalized_seen.add(normalized)
        deduped.append(warning.strip())
    return deduped


def _build_evidence_packet(
    section: ReportSection,
    request: dict[str, Any],
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], Any]:
    analysis = get_visualization_service().generate_grounded_report_analysis(
        data_rows=rows,
        user_query=request.get("analysis_query", ""),
        section_title=section.get("title", "Section"),
    )
    if not analysis.success:
        return (
            {
                "packet_id": f"{section.get('section_id', 'sec')}-packet-1",
                "section_id": section.get("section_id", ""),
                "request_id": request.get("request_id", ""),
                "sql": section.get("generated_sql", ""),
                "validated_sql": section.get("validated_sql", ""),
                "row_count": int(
                    section.get("sql_result", {}).get("row_count", 0) or 0
                ),
                "result_ref": section.get("result_ref"),
                "grouped_rows": [],
                "series_rows": [],
                "comparisons": [],
                "metrics": {},
                "denominators": {},
                "grain": request.get("expected_grain", "dataset"),
                "quality_warnings": [str(analysis.error or "Grounded analysis failed")],
                "evidence_paths": [],
                "underlying_observation_count": len(rows) if rows else None,
            },
            analysis,
        )

    computed_stats = analysis.computed_stats or {}
    grouped_rows = computed_stats.get("grouped_rows")
    series_rows = computed_stats.get("series")
    comparisons = computed_stats.get("comparisons")
    packet = {
        "packet_id": f"{section.get('section_id', 'sec')}-packet-1",
        "section_id": section.get("section_id", ""),
        "request_id": request.get("request_id", ""),
        "sql": section.get("generated_sql", ""),
        "validated_sql": section.get("validated_sql", ""),
        "row_count": int(
            computed_stats.get("row_count")
            or section.get("sql_result", {}).get("row_count", 0)
            or 0
        ),
        "result_ref": section.get("result_ref"),
        "grouped_rows": grouped_rows if isinstance(grouped_rows, list) else [],
        "series_rows": series_rows if isinstance(series_rows, list) else [],
        "comparisons": list(comparisons.values())
        if isinstance(comparisons, dict)
        else (comparisons if isinstance(comparisons, list) else []),
        "metrics": computed_stats.get("metrics", {})
        if isinstance(computed_stats.get("metrics"), dict)
        else {},
        "denominators": computed_stats.get("denominators", {})
        if isinstance(computed_stats.get("denominators"), dict)
        else {},
        "grain": request.get("expected_grain", "dataset"),
        "quality_warnings": _dedupe_quality_warnings(
            [
                str(item).strip()
                for item in (computed_stats.get("data_quality") or {}).get(
                    "warnings", []
                )
                if str(item).strip()
            ]
        ),
        "evidence_paths": [
            f"{section.get('section_id', 'sec')}.metrics",
            f"{section.get('section_id', 'sec')}.grouped_rows",
            f"{section.get('section_id', 'sec')}.series_rows",
        ],
        "underlying_observation_count": _underlying_observation_count(
            rows, computed_stats
        ),
    }
    return packet, analysis


def _normalize_claim_packet(
    raw: Any,
    section_id: str,
    index: int,
    *,
    valid_evidence_refs: set[str] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text", "")).strip()
    if not text:
        return None
    claim_type = str(raw.get("claim_type", "observation")).strip().lower()
    if claim_type not in {"observation", "comparison", "trend", "hypothesis"}:
        claim_type = "observation"
    confidence = str(raw.get("confidence", "medium")).strip().lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "medium"
    evidence_refs = []
    for ref in _as_string_list(raw.get("evidence_refs")):
        if valid_evidence_refs is not None and ref not in valid_evidence_refs:
            continue
        if ref not in evidence_refs:
            evidence_refs.append(ref)
    if not evidence_refs:
        return None
    return {
        "claim_id": str(raw.get("claim_id", "")).strip()
        or f"{section_id}-claim-{index}",
        "section_id": section_id,
        "claim_type": claim_type,
        "text": text,
        "evidence_refs": evidence_refs,
        "caveats": _as_string_list(raw.get("caveats")),
        "confidence": confidence,
        "recommendation_ready": bool(raw.get("recommendation_ready", False)),
    }


def _fallback_claim_packets(
    section: ReportSection, evidence_packets: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    packet = evidence_packets[0] if evidence_packets else {}
    warnings = _as_string_list(packet.get("quality_warnings"))
    grouped_rows = (
        packet.get("grouped_rows")
        if isinstance(packet.get("grouped_rows"), list)
        else []
    )
    metrics = packet.get("metrics") if isinstance(packet.get("metrics"), dict) else {}
    claims: list[dict[str, Any]] = []
    section_id = section.get("section_id", "sec")

    if grouped_rows:
        top_rows = grouped_rows[:2]
        summaries: list[str] = []
        for row in top_rows:
            if not isinstance(row, dict):
                continue
            parts = [f"{key}={value}" for key, value in row.items()]
            if parts:
                summaries.append(", ".join(parts))
        if summaries:
            claims.append(
                {
                    "claim_id": f"{section_id}-claim-1",
                    "section_id": section_id,
                    "claim_type": "comparison" if len(top_rows) > 1 else "observation",
                    "text": "; ".join(summaries),
                    "evidence_refs": packet.get("evidence_paths", [])[:2],
                    "caveats": warnings,
                    "confidence": section.get("section_confidence", "medium"),
                    "recommendation_ready": not warnings,
                }
            )
    elif metrics:
        metric_lines = []
        for key, value in list(metrics.items())[:3]:
            if isinstance(value, dict):
                display = value.get("display_value") or value.get("value")
            else:
                display = value
            metric_lines.append(f"{key}: {display}")
        if metric_lines:
            claims.append(
                {
                    "claim_id": f"{section_id}-claim-1",
                    "section_id": section_id,
                    "claim_type": "observation",
                    "text": "; ".join(metric_lines),
                    "evidence_refs": packet.get("evidence_paths", [])[:1],
                    "caveats": warnings,
                    "confidence": section.get("section_confidence", "medium"),
                    "recommendation_ready": not warnings,
                }
            )

    if not claims:
        claims.append(
            {
                "claim_id": f"{section_id}-claim-1",
                "section_id": section_id,
                "claim_type": "observation",
                "text": "Section evidence was retrieved, but only a conservative summary is safe from the available packet.",
                "evidence_refs": packet.get("evidence_paths", []),
                "caveats": warnings,
                "confidence": "low",
                "recommendation_ready": False,
            }
        )
    return claims, warnings


def _fallback_section_narrative(
    section: ReportSection,
    claims: list[dict[str, Any]],
    limitations: list[str],
    state: AgentState,
) -> str:
    is_vietnamese = _is_vietnamese_output(state)
    lines = [claim.get("text", "").strip() for claim in claims if claim.get("text")]
    if limitations:
        prefix = "Lưu ý:" if is_vietnamese else "Caveat:"
        lines.append(f"{prefix} {' '.join(limitations[:2])}")
    return "\n\n".join(line for line in lines if line).strip()


def _deterministic_critic_issues(state: AgentState, report_draft: str) -> list[str]:
    return run_report_validators(
        state.get("report_question_coverage"),
        state.get("report_unresolved_items"),
        state.get("report_sections"),
        report_draft,
    )


def section_retrieval_planner_node(state: AgentState) -> AgentState:
    section: SectionPlan = state.get("_current_section", {})
    evidence_request = _build_evidence_request(section)
    return {
        "_current_evidence_requests": [evidence_request],
        "_current_section_result": _base_report_section(section, {"status": "pending"}),
        "tool_history": [
            {
                "tool": "section_retrieval_planner",
                "status": "ok",
                "section_id": section.get("section_id", ""),
                "request_count": 1,
            }
        ],
    }


def section_evidence_executor_node(state: AgentState) -> AgentState:
    requests = state.get("_current_evidence_requests") or []
    section = state.get("_current_section", {})
    worker = get_sql_worker_graph()
    schema_context = state.get("report_schema_context") or state.get(
        "schema_context", ""
    )
    results: list[dict[str, Any]] = []
    base_section = state.get("_current_section_result") or _base_report_section(
        section, {"status": "pending"}
    )
    for request in requests:
        task_input: dict[str, Any] = {
            "task_id": request.get("request_id", section.get("section_id", "")),
            "query": request.get("analysis_query", ""),
            "original_user_query": state.get("report_original_request")
            or state.get("report_request")
            or state.get("user_query", ""),
            "target_db_path": state.get("target_db_path", ""),
            "schema_context": schema_context,
            "session_context": state.get("session_context", ""),
            "xml_database_context": state.get("xml_database_context", ""),
            "status": "pending",
            "requires_visualization": False,
            "run_id": state.get("run_id", ""),
            "thread_id": state.get("thread_id", ""),
        }
        results.append(worker.invoke(task_input))

    first = (
        results[0] if results else {"status": "failed", "error": "No evidence request"}
    )
    report_section = _base_report_section(section, first)
    report_section["evidence_requests"] = requests
    if report_section.get("status") == "failed":
        error = str(first.get("error", "Unknown")).strip() or "Unknown"
        report_section["insight_markdown"] = (
            f"Không thể tạo insight cho mục này: {error}"
        )
        report_section["limitations"] = [error]
    return {
        "_current_evidence_results": results,
        "_current_section_result": report_section,
    }


def section_evidence_packet_builder_node(state: AgentState) -> AgentState:
    report_section = state.get("_current_section_result") or {}
    if report_section.get("status") == "failed":
        return {
            "_current_section_result": report_section,
            "_current_evidence_packets": [],
        }

    requests = state.get("_current_evidence_requests") or []
    request = (
        requests[0]
        if requests
        else _build_evidence_request(state.get("_current_section", {}))
    )
    rows = _load_report_rows(report_section)
    evidence_packet, analysis = _build_evidence_packet(report_section, request, rows)
    report_section["evidence_packets"] = [evidence_packet]
    report_section["computed_stats"] = (
        analysis.computed_stats if analysis.success else None
    )
    report_section["chart_manifest"] = (
        analysis.chart_manifest if analysis.success else None
    )
    report_section["chart_html"] = analysis.chart_html if analysis.success else None
    report_section["sandbox_analysis"] = {
        "success": bool(analysis.success),
        "execution_time_ms": analysis.execution_time_ms,
        "code_executed": analysis.code_executed,
        "error": analysis.error,
    }
    if not analysis.success:
        report_section["status"] = "failed"
        report_section["analysis_status"] = "failed"
        report_section["error"] = analysis.error or "Grounded analysis failed"
        report_section["insight_markdown"] = (
            f"Không thể phân tích dữ liệu: {analysis.error}"
        )
        report_section["limitations"] = [str(analysis.error)]
        return {
            "_current_evidence_packets": [evidence_packet],
            "_current_section_result": report_section,
        }

    report_section["analysis_status"] = "done"
    report_section = _validate_section_semantics(report_section)
    return {
        "_current_evidence_packets": [evidence_packet],
        "_current_analysis_result": analysis,
        "_current_section_result": report_section,
    }


def section_chart_builder_node(state: AgentState) -> AgentState:
    report_section = state.get("_current_section_result") or {}
    analysis = state.get("_current_analysis_result")
    if report_section.get("status") == "failed" or analysis is None:
        return {"_current_section_result": report_section}

    needs_viz = bool(report_section.get("requires_visualization", True))
    image_data = analysis.image_data if needs_viz else None
    chart_url = None
    rel_path = None
    if image_data:
        rel_path = save_section_chart_to_file(
            image_data=image_data,
            section_id=report_section.get("section_id", "unknown"),
            image_format=analysis.image_format or "png",
            thread_id=state.get("thread_id", "default"),
            turn_number=state.get("conversation_turn", 0),
        )
        if rel_path:
            chart_url = chart_url_from_path(rel_path)

    report_section["chart_image_url"] = chart_url
    report_section["chart_image_format"] = analysis.image_format if needs_viz else None
    report_section["visualization"] = {
        "success": bool(chart_url),
        "image_url": chart_url,
        "image_format": analysis.image_format,
        "image_size_bytes": len(image_data) if image_data else 0,
        "execution_time_ms": analysis.execution_time_ms,
        "error": analysis.error,
        "artifact_path": rel_path,
    }
    packets = report_section.get("evidence_packets", []) or []
    if packets and rel_path:
        packet = dict(packets[0])
        evidence_paths = _as_string_list(packet.get("evidence_paths"))
        evidence_paths.append(rel_path)
        packet["evidence_paths"] = evidence_paths
        report_section["evidence_packets"] = [packet]
    return {"_current_section_result": report_section}


def section_claim_builder_node(state: AgentState) -> AgentState:
    report_section = state.get("_current_section_result") or {}
    evidence_packets = report_section.get("evidence_packets", []) or []
    if report_section.get("status") == "failed":
        return {"_current_claims": [], "_current_section_result": report_section}

    raw_output: dict[str, Any] = {}
    try:
        settings = load_settings()
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=prompt_manager.report_claim_builder_messages(
                query=state.get("report_original_request")
                or state.get("report_request")
                or state.get("user_query", ""),
                section_plan=_truncate_json_for_prompt(
                    report_section.get("plan") or {}, 4000
                ),
                evidence_packets=_truncate_json_for_prompt(
                    {"evidence_packets": evidence_packets}, 8000
                ),
            ),
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
        raw_output = _extract_first_json_object(content) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Report claim builder failed for section {id}: {error}",
            id=report_section.get("section_id", "?"),
            error=str(exc),
        )

    valid_evidence_refs = {
        ref
        for packet in evidence_packets
        for ref in _as_string_list(packet.get("evidence_paths"))
    }
    claims = [
        claim
        for index, raw in enumerate(raw_output.get("claims", []), start=1)
        if (
            claim := _normalize_claim_packet(
                raw,
                report_section.get("section_id", "sec"),
                index,
                valid_evidence_refs=valid_evidence_refs,
            )
        )
    ]
    limitations = _as_string_list(raw_output.get("limitations"))
    if not claims:
        claims, limitations = _fallback_claim_packets(report_section, evidence_packets)

    report_section["claims"] = claims
    merged_limitations = [
        *(_as_string_list(report_section.get("limitations"))),
        *limitations,
    ]
    report_section["limitations"] = _dedupe_quality_warnings(merged_limitations)
    report_section["insight_citations"] = [
        {"json_path": ref, "value": "evidence"}
        for claim in claims
        for ref in claim.get("evidence_refs", [])
    ]
    return {"_current_claims": claims, "_current_section_result": report_section}


def section_narrator_node(state: AgentState) -> AgentState:
    report_section = state.get("_current_section_result") or {}
    if report_section.get("status") == "failed":
        return {"_report_sections_raw": [report_section]}

    claims = report_section.get("claims", []) or []
    narrative = ""
    limitations = _as_string_list(report_section.get("limitations"))
    try:
        settings = load_settings()
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=prompt_manager.report_section_narrator_messages(
                query=state.get("report_original_request")
                or state.get("report_request")
                or state.get("user_query", ""),
                section_plan=_truncate_json_for_prompt(
                    report_section.get("plan") or {}, 4000
                ),
                claims=_truncate_json_for_prompt({"claims": claims}, 6000),
            ),
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
        narrative = str(parsed.get("narrative", "")).strip()
        limitations.extend(_as_string_list(parsed.get("limitations")))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Report section narrator failed for section {id}: {error}",
            id=report_section.get("section_id", "?"),
            error=str(exc),
        )

    if not narrative:
        narrative = _fallback_section_narrative(
            report_section, claims, limitations, state
        )
    report_section["narrative"] = narrative
    report_section["insight_markdown"] = narrative
    report_section["limitations"] = _dedupe_quality_warnings(limitations)
    report_section["validation"] = {
        "claim_count": len(claims),
        "evidence_packet_count": len(report_section.get("evidence_packets", []) or []),
    }
    report_section = _apply_semantic_caveat(report_section, state)
    return {"_report_sections_raw": [report_section]}


def section_pipeline_node(state: AgentState) -> AgentState:
    current = state
    for stage in (
        section_retrieval_planner_node,
        section_evidence_executor_node,
        section_evidence_packet_builder_node,
        section_chart_builder_node,
        section_claim_builder_node,
        section_narrator_node,
    ):
        current = {**current, **stage(current)}
    return {"_report_sections_raw": current.get("_report_sections_raw", [])}


# ---------------------------------------------------------------------------
# NODE 7: Sections Sort — collect fan-in results, sort by section_order
# ---------------------------------------------------------------------------


def sections_sort_node(state: AgentState) -> AgentState:
    """Collect all sections from Send() fan-in, sort by original planner order."""
    raw_sections = state.get("_report_sections_raw") or []
    sorted_sections = sorted(raw_sections, key=lambda s: s.get("section_order", 0))
    failed = [s for s in sorted_sections if s.get("status") == "failed"]
    return {
        "report_sections": sorted_sections,
        "report_status": "writing",
        "errors": [
            {
                "category": "REPORT_SECTION_ERROR",
                "message": str(s.get("error", "Unknown")),
                "section_id": s.get("section_id"),
            }
            for s in failed
        ],
        "tool_history": [
            {
                "tool": "sections_sort",
                "status": "ok",
                "total": len(sorted_sections),
                "failed": len(failed),
            }
        ],
    }


# ---------------------------------------------------------------------------
# NODE 8: Writer
# ---------------------------------------------------------------------------


def _section_writer_payload(section: ReportSection) -> dict[str, Any]:
    return {
        "section_id": section.get("section_id"),
        "title": section.get("title"),
        "business_question": section.get("business_question"),
        "analysis_query": section.get("analysis_query"),
        "analysis_type": section.get("analysis_type", "descriptive"),
        "inclusion_reason": section.get("inclusion_reason", ""),
        "addresses_question_ids": section.get("addresses_question_ids", []),
        "tests_hypothesis_ids": section.get("tests_hypothesis_ids", []),
        "status": section.get("status"),
        "analysis_status": section.get("analysis_status"),
        "section_confidence": section.get("section_confidence", "medium"),
        "claims": section.get("claims", []),
        "evidence_packets": section.get("evidence_packets", []),
        "insight_markdown": _truncate_text(section.get("insight_markdown", ""), 3000),
        "citations": section.get("insight_citations", []),
        "computed_stats": _writer_stats_payload(section),
        "semantic_warnings": section.get("semantic_warnings", []),
        "limitations": section.get("limitations", []),
    }


def report_assembler_node(state: AgentState) -> AgentState:
    settings = load_settings()
    report_plan = json.dumps(
        state.get("report_plan", {}), ensure_ascii=False, indent=2, default=str
    )
    section_results = json.dumps(
        [
            _section_writer_payload(section)
            for section in state.get("report_sections", [])
        ],
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    messages = prompt_manager.report_writer_messages(
        query=state.get("report_original_request")
        or state.get("report_request")
        or state.get("user_query", ""),
        report_plan=report_plan,
        section_results=section_results,
        critic_feedback=state.get("critic_feedback", ""),
        domain_context=_report_domain_context(state),
        coverage_summary=json.dumps(
            state.get("report_question_coverage", {}),
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        unresolved_items=json.dumps(
            state.get("report_unresolved_items", []),
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
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

    if not report_draft:
        report_draft = _build_safe_report_markdown(state)

    report_draft = _cleanup_report_markdown(report_draft)
    report_draft = _ensure_report_recommendations(report_draft, state)

    return {
        "report_draft": report_draft,
        "report_status": "critiquing",
        "tool_history": [
            {
                "tool": "report_assembler",
                "status": "ok",
                "draft_length": len(report_draft),
            }
        ],
    }


# ---------------------------------------------------------------------------
# NODE 9: Critic
# ---------------------------------------------------------------------------


def _section_critic_payload(section: ReportSection) -> dict[str, Any]:
    stats = section.get("computed_stats", {})
    if isinstance(stats, dict):
        stats = {
            k: (v[:20] if isinstance(v, list) and len(v) > 20 else v)
            for k, v in stats.items()
        }
    return {
        "section_id": section.get("section_id"),
        "title": section.get("title"),
        "business_question": section.get("business_question"),
        "status": section.get("status"),
        "analysis_type": section.get("analysis_type", "descriptive"),
        "addresses_question_ids": section.get("addresses_question_ids", []),
        "tests_hypothesis_ids": section.get("tests_hypothesis_ids", []),
        "section_confidence": section.get("section_confidence", "medium"),
        "insight_markdown": _truncate_text(section.get("insight_markdown", ""), 3000),
        "citations": section.get("insight_citations", []),
        "computed_stats": stats,
        "semantic_warnings": section.get("semantic_warnings", []),
        "limitations": section.get("limitations", []),
    }


def report_validator_node(state: AgentState) -> AgentState:
    settings = load_settings()
    section_results = json.dumps(
        [
            _section_critic_payload(section)
            for section in state.get("report_sections", [])
        ],
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    report_draft = state.get("report_draft", "")
    previous_feedback_hash = state.get("report_feedback_hash", "")
    current_draft_hash = _stable_hash(report_draft)

    verdict = "APPROVED"
    issues: list[str] = []
    summary = "Draft is grounded."
    try:
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=prompt_manager.report_critic_messages(
                query=state.get("report_original_request")
                or state.get("report_request")
                or state.get("user_query", ""),
                section_results=section_results,
                report_draft=report_draft,
                coverage_summary=json.dumps(
                    state.get("report_question_coverage", {}),
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                unresolved_items=json.dumps(
                    state.get("report_unresolved_items", []),
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
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
        issues = [
            str(item).strip() for item in parsed.get("issues", []) if str(item).strip()
        ]
        summary = str(parsed.get("summary", summary)).strip() or summary
    except Exception as exc:  # noqa: BLE001
        logger.warning("Report critic failed: {error}", error=str(exc))

    deterministic_issues = _deterministic_critic_issues(state, report_draft)
    for issue in deterministic_issues:
        if issue not in issues:
            issues.append(issue)
    if deterministic_issues:
        verdict = "REVISE"
        if summary == "Draft is grounded.":
            summary = (
                "Draft needs revisions to preserve required caveats and structure."
            )

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
        "validator_feedback": feedback,
        "validator_issues": issues,
        "validator_verdict": verdict,
        "critic_verdict": verdict,
        "critic_issues": issues,
        "report_feedback_hash": feedback_hash,
        "report_draft_hash": current_draft_hash,
        "report_status": "writing" if should_revise else "done",
        "critic_decision": "revise" if should_revise else "finalize",
        "validator_decision": "revise" if should_revise else "finalize",
        "tool_history": [
            {
                "tool": "report_validator",
                "status": "ok",
                "verdict": verdict,
                "iteration": critic_iteration,
                "issue_count": len(issues),
            }
        ],
    }


def _validator_router(
    state: AgentState,
) -> Literal["report_assembler", "report_finalize"]:
    return (
        "report_assembler"
        if state.get("validator_decision", state.get("critic_decision")) == "revise"
        else "report_finalize"
    )


# ---------------------------------------------------------------------------
# NODE 10: Finalize — save report.md to disk and package output
# ---------------------------------------------------------------------------


def report_finalize_node(state: AgentState) -> AgentState:
    critic_verdict = str(
        state.get("validator_verdict", state.get("critic_verdict", "APPROVED"))
    ).upper()
    used_safe_fallback = critic_verdict == "REVISE"
    if used_safe_fallback:
        report_markdown = _build_safe_report_markdown(state)
    else:
        report_markdown = _cleanup_report_markdown(state.get("report_draft", ""))
    plan_title = state.get("report_plan", {}).get("title", "Report")
    errors = state.get("errors", [])
    answer = (
        "Đây là report của bạn. Bấm vào nút Report để xem bản trình bày đầy đủ."
        if _is_vietnamese_output(state)
        else "Here is your report. Open the Report panel to view the full write-up."
    )
    confidence, confidence_rationale = _derive_report_confidence(
        state, used_safe_fallback=used_safe_fallback
    )
    artifact_thread = state.get("thread_id", "default")
    artifact_turn = int(state.get("conversation_turn", 0) or 0)
    report_markdown_path = save_report_markdown_to_file(
        markdown=report_markdown,
        thread_id=artifact_thread,
        turn_number=artifact_turn,
    )

    payload = {
        "answer": answer,
        "report_markdown": report_markdown
        or f"# {plan_title}\n\nNo report content was generated.",
        "report_sections": [
            _report_section_payload(section)
            for section in state.get("report_sections", [])
            if section.get("status") == "done"
        ],
        "evidence": [
            "intent=sql",
            f"rows={sum(section.get('sql_result', {}).get('row_count', 0) for section in state.get('report_sections', []))}",
        ],
        "confidence": confidence,
        "confidence_rationale": confidence_rationale,
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
        "result_metadata": {
            "artifact_thread_id": artifact_thread,
            "artifact_turn": artifact_turn,
            "report_markdown_path": report_markdown_path,
        },
    }
    return {
        "final_answer": answer,
        "final_payload": payload,
        "report_final": payload["report_markdown"],
        "report_status": "done",
        "intent": "sql",
        "confidence": payload["confidence"],
        "report_confidence_rationale": confidence_rationale,
        "response_mode": "report",
        "tool_history": [
            {
                "tool": "report_finalize",
                "status": "ok",
                "section_count": len(state.get("report_sections", [])),
                "used_safe_fallback": used_safe_fallback,
            }
        ],
        "step_count": state.get("step_count", 0) + 1,
    }


def report_writer_node(state: AgentState) -> AgentState:
    return report_assembler_node(state)


def report_critic_node(state: AgentState) -> AgentState:
    return report_validator_node(state)


# ---------------------------------------------------------------------------
# Graph Construction
# ---------------------------------------------------------------------------


def build_report_subgraph():
    """Build the report subgraph with staged evidence-first section execution."""
    builder = StateGraph(AgentState)

    builder.add_node(
        "report_request_grounder",
        _instrument_node("report_request_grounder_node", report_request_grounder_node),
    )
    builder.add_node(
        "profiler_sampler",
        _instrument_node("profiler_sampler_node", profiler_sampler_node),
    )
    builder.add_node(
        "report_dataset_profiler",
        _instrument_node("report_dataset_profiler_node", report_dataset_profiler_node),
    )
    builder.add_node(
        "report_brief_builder",
        _instrument_node("report_brief_builder_node", report_brief_builder_node),
    )
    builder.add_node(
        "report_planner",
        _instrument_node("report_planner_node", report_planner_node),
    )
    builder.add_node(
        "section_pipeline",
        _instrument_node("section_pipeline_node", section_pipeline_node),
    )
    builder.add_node(
        "sections_sort",
        _instrument_node("sections_sort_node", sections_sort_node),
    )
    builder.add_node(
        "report_assembler",
        _instrument_node("report_assembler_node", report_assembler_node),
    )
    builder.add_node(
        "report_validator",
        _instrument_node("report_validator_node", report_validator_node),
    )
    builder.add_node(
        "report_finalize",
        _instrument_node("report_finalize_node", report_finalize_node),
    )

    # Edges
    builder.add_edge(START, "report_request_grounder")
    builder.add_edge("report_request_grounder", "profiler_sampler")
    builder.add_edge("profiler_sampler", "report_dataset_profiler")
    builder.add_edge("report_dataset_profiler", "report_brief_builder")
    builder.add_edge("report_brief_builder", "report_planner")

    # Send() fan-out: planner → N × section_pipeline (parallel)
    builder.add_conditional_edges(
        "report_planner",
        fan_out_sections,
        ["section_pipeline"],
    )

    builder.add_edge("section_pipeline", "sections_sort")

    builder.add_edge("sections_sort", "report_assembler")
    builder.add_edge("report_assembler", "report_validator")
    builder.add_conditional_edges(
        "report_validator",
        _validator_router,
        {
            "report_assembler": "report_assembler",
            "report_finalize": "report_finalize",
        },
    )
    builder.add_edge("report_finalize", END)

    return builder.compile()
