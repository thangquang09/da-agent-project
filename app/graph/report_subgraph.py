from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.config import load_settings
from app.graph.sql_worker_graph import get_sql_worker_graph
from app.graph.state import AgentState, ReportPlan, ReportSection
from app.llm import LLMClient
from app.logger import logger
from app.observability import get_current_tracer
from app.prompts import prompt_manager
from app.tools.get_schema import get_schema_overview
from app.tools.query_sql import query_sql
from app.artifacts.file_store import get_artifact_file_store
from app.artifacts.helpers import (
    save_section_chart_to_file,
    read_chart_bytes,
    chart_url_from_path,
)
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


def _first_nonempty_paragraph(text: str) -> str:
    for block in re.split(r"\n\s*\n", text or ""):
        cleaned = block.strip()
        if cleaned:
            return cleaned
    return ""


def _is_probably_vietnamese(text: str) -> bool:
    lowered = (text or "").lower()
    if re.search(
        r"[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]",
        lowered,
    ):
        return True
    return any(
        token in lowered
        for token in ["hãy", "báo cáo", "dữ liệu", "phân tích", "tỷ lệ", "cảnh báo"]
    )


def _build_cautious_recommendations(state: AgentState) -> list[str]:
    recommendations: list[str] = []
    if any(
        section.get("semantic_warnings") for section in state.get("report_sections", [])
    ):
        recommendations.append(
            "Xác minh lại metric definition, grain phân tích, và cách tính các tỷ lệ trước khi dùng report này cho quyết định quan trọng."
        )
    if any(
        section.get("section_confidence") == "low"
        for section in state.get("report_sections", [])
    ):
        recommendations.append(
            "Ưu tiên kiểm tra thêm các section có confidence thấp bằng truy vấn sâu hơn hoặc phân tích thủ công trước khi diễn giải mạnh."
        )
    recommendations.append(
        "Dùng report này như bước mô tả và định hướng điều tra tiếp theo, không coi là bằng chứng nhân quả hay khuyến nghị can thiệp cuối cùng."
    )
    return recommendations[:3]


def _ensure_report_recommendations(text: str, state: AgentState) -> str:
    if re.search(r"^##\s+Recommendations\b", text, flags=re.IGNORECASE | re.MULTILINE):
        return text
    recommendations = _build_cautious_recommendations(state)
    if not recommendations:
        return text
    lines = [text.rstrip(), "", "## Recommendations", ""]
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


def _soften_overclaim_language(text: str, *, is_vietnamese: bool) -> str:
    softened = text
    if is_vietnamese:
        replacements = {
            "ảnh hưởng quyết định đến khả năng sống sót": "có thể liên quan mạnh về mặt mô tả đến khả năng sống sót",
            "có ảnh hưởng mạnh đến tỷ lệ sống sót": "có liên hệ mô tả rõ với tỷ lệ sống sót",
            "có ảnh hưởng mạnh đến": "có liên hệ mô tả rõ với",
            "cho thấy rõ ràng": "gợi ý khá rõ",
            "xác nhận giả thuyết": "phù hợp với giả thuyết mô tả",
            "là yếu tố quan trọng ảnh hưởng": "có thể là một yếu tố liên quan đến",
            "phản ánh rõ ràng": "gợi ý",
        }
    else:
        replacements = {
            "decisively affected survival": "may be descriptively associated with survival",
            "strongly affects": "is descriptively associated with",
            "clearly shows": "suggests",
            "confirms the hypothesis": "is consistent with the descriptive hypothesis",
        }
    for source, target in replacements.items():
        softened = softened.replace(source, target)
    return softened


def _build_safe_report_markdown(state: AgentState) -> str:
    plan_title = state.get("report_plan", {}).get("title", "Report")
    sections = [
        section
        for section in state.get("report_sections", [])
        if section.get("status") == "done"
    ]
    lines = [f"# {plan_title}", "", "## Tóm tắt tổng quan", ""]

    summary = (
        "Báo cáo dưới đây chỉ tổng hợp các phát hiện đã được grounding ở từng mục. "
        "Một số phần diễn giải mức cao đã bị lược bỏ do bản nháp trước đó chưa vượt qua bước phản biện."
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

    all_limitations = [
        limitation.strip()
        for section in sections
        for limitation in section.get("limitations", [])
        if limitation and limitation.strip()
    ]
    lines.extend(["", "## Kết luận", ""])
    lines.append(
        "Các kết luận dưới đây chỉ nên được hiểu là phần tổng hợp an toàn từ những mục đã có evidence trực tiếp."
    )
    if all_limitations:
        lines.append(
            "Các hạn chế dữ liệu và phạm vi phân tích đã được ghi rõ trong từng mục tương ứng, và cần được xem xét trước khi đưa ra quyết định."
        )

    recommendations: list[str] = []
    if all_limitations:
        recommendations.append(
            "Rà soát kỹ các hạn chế dữ liệu đã được nêu trong từng mục trước khi chuyển các phát hiện này thành quyết định vận hành."
        )
    if sections:
        recommendations.append(
            "Đối chiếu lại các phát hiện quan trọng nhất với metric definition, grain phân tích, và câu hỏi kinh doanh gốc trước khi hành động."
        )
    recommendations.append(
        "Nếu cần quyết định có tác động lớn, hãy chạy thêm phân tích chuyên sâu hoặc kiểm định bổ sung thay vì chỉ dựa vào bản tóm tắt an toàn này."
    )

    lines.extend(["", "## Recommendations", ""])
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
        "limitations": section.get("limitations", []),
        "analysis_type": section.get("analysis_type", "descriptive"),
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
    elif row_count < 5:
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

    deduped_warnings: list[str] = []
    for item in warnings:
        if item not in deduped_warnings:
            deduped_warnings.append(item)

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

    if not reasons:
        reasons.append(
            "All completed sections were grounded and the draft passed the critic without flagged issues."
        )
    return confidence, " ".join(reasons)


def _default_report_plan(query: str) -> ReportPlan:
    return {
        "title": f"Report: {query[:80]}".strip(),
        "executive_summary_instruction": "Summarize the most important findings from the available data.",
        "sections": [
            {
                "section_id": "1",
                "title": "Overview",
                "analysis_query": query,
                "analysis_type": "descriptive",
                "target_metrics": [],
                "target_dimensions": [],
                "expected_grain": "dataset",
                "confidence_notes": "Fallback plan due to missing profiler guidance.",
                "status": "pending",
            },
            {
                "section_id": "2",
                "title": "Key Breakdown",
                "analysis_query": f"Provide a useful breakdown for: {query}",
                "analysis_type": "comparative",
                "target_metrics": [],
                "target_dimensions": [],
                "expected_grain": "segment",
                "confidence_notes": "Fallback plan due to missing profiler guidance.",
                "status": "pending",
            },
        ],
        "conclusion_instruction": "Conclude with grounded findings and limitations.",
    }


# ---------------------------------------------------------------------------
# NODE 1: Profiler Sampler — runs SQL to fetch 100 random rows + column stats
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
    db_path_raw = state.get("target_db_path", "")
    db_path = Path(db_path_raw) if db_path_raw else None

    # Prioritize tables from uploaded data context
    table_contexts = state.get("table_contexts") or {}
    uploaded_tables = list(table_contexts.keys())
    if uploaded_tables:
        # Only profile tables that have user-provided business context
        tables = [t for t in uploaded_tables if t in all_tables][:2]
        if not tables:
            tables = all_tables[:2]
    else:
        tables = all_tables[:2]

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
            # 100 random rows
            sample_sql = f'SELECT * FROM "{table}" ORDER BY RANDOM() LIMIT 100'
            sample_result = query_sql(sample_sql, db_path=db_path)
            sample_rows = sample_result.get("rows", [])

            # Column-level summary stats (count, distinct, nulls) — cap at 15 columns
            columns = sample_result.get("columns", [])[:15]
            col_stats: list[dict[str, Any]] = []
            for col in columns:
                try:
                    stats_sql = (
                        f"SELECT "
                        f"COUNT(*) AS total_rows, "
                        f'COUNT(DISTINCT "{col}") AS distinct_count, '
                        f'SUM(CASE WHEN "{col}" IS NULL THEN 1 ELSE 0 END) AS null_count '
                        f'FROM "{table}"'
                    )
                    stats_result = query_sql(stats_sql, db_path=db_path)
                    row = (stats_result.get("rows") or [{}])[0]
                    col_stats.append(
                        {
                            "column": col,
                            "total_rows": row.get("total_rows", 0),
                            "distinct_count": row.get("distinct_count", 0),
                            "null_count": row.get("null_count", 0),
                        }
                    )
                except Exception:  # noqa: BLE001
                    col_stats.append({"column": col, "error": "stats query failed"})

            sample_data[table] = {
                "sample_rows": sample_rows[:100],
                "sample_count": len(sample_rows),
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
# NODE 2: Profiler Analyzer — LLM reads schema + sample data → domain context
# ---------------------------------------------------------------------------


def profiler_analyzer_node(state: AgentState) -> AgentState:
    """LLM-based profiler: reads schema + ACTUAL sample data → domain analysis + sections."""
    query = state.get("report_request") or state.get("user_query", "")
    sample_data = state.get("report_sample_data") or {}

    # Build a compact sample summary for the prompt (limit to ~8K chars)
    sample_summary_parts: list[str] = []
    for table_name, table_info in sample_data.items():
        if isinstance(table_info, dict) and "error" not in table_info:
            rows = table_info.get("sample_rows", [])
            col_stats = table_info.get("column_stats", [])
            # Show first 10 sample rows (compact)
            row_preview = json.dumps(rows[:10], ensure_ascii=False, default=str)
            if len(row_preview) > 2000:
                row_preview = row_preview[:2000] + "..."
            stats_text = json.dumps(col_stats, ensure_ascii=False, default=str)
            if len(stats_text) > 1500:
                stats_text = stats_text[:1500] + "..."
            sample_summary_parts.append(
                f"### Table: {table_name}\n"
                f"Total sample rows: {table_info.get('sample_count', 0)}\n"
                f"Columns: {', '.join(table_info.get('columns', []))}\n"
                f"Column stats:\n{stats_text}\n"
                f"Sample rows (first 10):\n{row_preview}"
            )
    sample_summary = (
        "\n\n".join(sample_summary_parts)
        if sample_summary_parts
        else "(no sample data available)"
    )

    # Include user-provided business context from paired uploads
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
            "profiler_analyzer: LLM response length={len}, preview={preview}",
            len=len(content),
            preview=content[:300],
        )
        profile = _extract_first_json_object(content) or {}
        logger.info(
            "profiler_analyzer: domain_summary={dom}, suggested_sections={n}",
            dom=profile.get("domain_summary", "")[:100],
            n=len(profile.get("suggested_sections", [])),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Report data profiler failed: {error}", error=str(exc))
        profile = {}

    return {
        "report_data_profile": profile,
        "tool_history": [
            {
                "tool": "profiler_analyzer",
                "status": "ok" if profile else "fallback",
                "analytical_angles": profile.get("analytical_angles", []),
            }
        ],
    }


# ---------------------------------------------------------------------------
# NODE 3: Planner — produces _report_sections_planned for Send()
# ---------------------------------------------------------------------------


def report_planner_node(state: AgentState) -> AgentState:
    query = state.get("report_request") or state.get("user_query", "")
    settings = load_settings()

    profile = state.get("report_data_profile") or {}
    suggested = profile.get("suggested_sections") or []
    domain_context = profile.get("domain_summary", "")

    logger.info(
        "report_planner: profile keys={keys}, suggested_sections={n}, domain_context={ctx}",
        keys=list(profile.keys()),
        n=len(suggested),
        ctx=domain_context[:100] if domain_context else "(empty)",
    )

    plan: dict[str, Any] | None = None

    if suggested and isinstance(suggested, list):
        logger.info(
            "Report planner: {n} suggested sections from profiler: {titles}",
            n=len(suggested),
            titles=[s.get("title", "?") for s in suggested[:5]],
        )
        plan = {
            "title": f"Report: {query[:80]}".strip(),
            "executive_summary_instruction": (
                f"Summarize the most important findings. "
                f"Domain context: {domain_context}"
            ),
            "sections": suggested,
            "conclusion_instruction": (
                "Conclude with grounded findings, limitations, and 2-3 actionable recommendations."
            ),
            "domain_context": domain_context,
        }
        logger.info(
            "Report planner: using profiler-suggested sections (count={n})",
            n=len(suggested),
        )
    else:
        # Fallback: include sample data summary so Planner isn't blind
        sample_data = state.get("report_sample_data") or {}
        sample_summary = ""
        for table_name, table_info in sample_data.items():
            if isinstance(table_info, dict) and "error" not in table_info:
                cols = ", ".join(table_info.get("columns", [])[:10])
                sample_summary += f"Table '{table_name}': columns=[{cols}]\n"

        messages = prompt_manager.report_planner_messages(
            query=query,
            session_context=state.get("session_context", ""),
            xml_database_context=state.get("xml_database_context", ""),
        )
        # Inject sample data hint into the last user message if available
        if sample_summary:
            messages[-1]["content"] += f"\n\nAvailable data preview:\n{sample_summary}"
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
                "analysis_type": _normalize_analysis_type(
                    raw.get("analysis_type"),
                    query=analysis_query,
                    title=str(raw.get("title", f"Section {idx}")),
                ),
                "target_metrics": _as_string_list(raw.get("target_metrics")),
                "target_dimensions": _as_string_list(raw.get("target_dimensions")),
                "expected_grain": str(raw.get("expected_grain", "dataset")).strip()
                or "dataset",
                "confidence_notes": str(raw.get("confidence_notes", "")).strip(),
                "requires_visualization": bool(raw.get("requires_visualization", True)),
                "section_order": idx,
                "status": "pending",
                "analysis_status": "pending",
            }
        )

    if not sections:
        plan = _default_report_plan(query)
        sections = [
            {**s, "section_order": i + 1} for i, s in enumerate(plan["sections"])
        ]
    else:
        sections = sections[:5]
        plan["sections"] = sections

    if domain_context:
        plan["domain_context"] = domain_context

    return {
        "report_plan": plan,
        "_report_sections_planned": sections,
        "report_status": "executing",
        "tool_history": [
            {
                "tool": "report_planner",
                "status": "ok",
                "section_count": len(sections),
                "used_profiler": bool(suggested),
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
# NODE 4: Section Pipeline — per-section: SQL → sandbox → insight
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
    domain_ctx = (state.get("report_data_profile") or {}).get("domain_summary", "")
    text_content = (
        f"Original report request:\n{state.get('report_request') or state.get('user_query', '')}\n\n"
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
    is_vietnamese = _is_probably_vietnamese(
        state.get("report_request") or state.get("user_query", "")
    )
    if warnings:
        insight_markdown = _soften_overclaim_language(
            insight_markdown, is_vietnamese=is_vietnamese
        )
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


def _deterministic_critic_issues(state: AgentState, report_draft: str) -> list[str]:
    issues: list[str] = []
    if not re.search(
        r"^##\s+Recommendations\b", report_draft, flags=re.IGNORECASE | re.MULTILINE
    ):
        issues.append("Draft is missing the required '## Recommendations' section.")

    lower_draft = report_draft.lower()
    strong_claim_markers = [
        "yếu tố quyết định",
        "ảnh hưởng quyết định",
        "có ảnh hưởng mạnh",
        "ảnh hưởng rất lớn",
        "cho thấy",
        "khẳng định",
        "proves",
        "decisive factor",
    ]
    caveat_markers = [
        "thận trọng",
        "caveat",
        "giới hạn",
        "không chứng minh",
        "descriptive",
        "cần xác minh",
    ]
    if any(marker in lower_draft for marker in strong_claim_markers):
        warned_sections = [
            section
            for section in state.get("report_sections", [])
            if section.get("semantic_warnings")
            or section.get("section_confidence") != "high"
        ]
        if warned_sections and not any(
            marker in lower_draft for marker in caveat_markers
        ):
            issues.append(
                "Draft makes strong analytical claims without preserving caveats from semantically weak or warning-heavy sections."
            )
    return issues


def section_pipeline_node(state: AgentState) -> AgentState:
    """Per-section pipeline: SQL worker → sandbox analysis → insight generation.

    Runs as a Send() target — each section gets its own invocation.
    Returns the completed section into ``_report_sections_raw`` (operator.add reducer).
    """
    section: ReportSection = state.get("_current_section", {})
    section_id = section.get("section_id", "?")
    title = section.get("title", "Section")
    logger.info(
        "section_pipeline: processing section {id} '{title}'",
        id=section_id,
        title=title,
    )

    # --- Step 1: SQL Worker ---
    worker = get_sql_worker_graph()
    schema_context = state.get("report_schema_context") or state.get(
        "schema_context", ""
    )
    task_input: dict[str, Any] = {
        "task_id": section_id,
        "query": section.get("analysis_query", ""),
        "original_user_query": state.get("report_request")
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
    result = worker.invoke(task_input)
    status = "done" if result.get("status") == "success" else "failed"

    report_section: ReportSection = {
        "section_id": section_id,
        "title": title,
        "analysis_query": section.get("analysis_query", ""),
        "analysis_type": _normalize_analysis_type(
            section.get("analysis_type"),
            query=section.get("analysis_query", ""),
            title=title,
        ),
        "target_metrics": section.get("target_metrics", []),
        "target_dimensions": section.get("target_dimensions", []),
        "expected_grain": section.get("expected_grain", "dataset"),
        "confidence_notes": section.get("confidence_notes", ""),
        "requires_visualization": bool(section.get("requires_visualization", True)),
        "section_order": section.get("section_order", 0),
        "sql_result": result.get("sql_result", {}),
        "result_ref": result.get("result_ref"),
        "raw_result_ref": result.get("result_ref"),
        "status": status,
        "analysis_status": "failed" if status == "failed" else "pending",
        "semantic_warnings": [],
        "semantic_status": "ok",
        "section_confidence": "high",
        "error": result.get("error"),
        "generated_sql": result.get("generated_sql", ""),
        "validated_sql": result.get("validated_sql", ""),
    }

    if status == "failed":
        report_section["insight_markdown"] = (
            f"Không thể tạo insight cho mục này: {result.get('error', 'Unknown')}"
        )
        report_section["insight_citations"] = []
        report_section["limitations"] = [str(result.get("error", "Unknown"))]
        return {"_report_sections_raw": [report_section]}

    # --- Step 2: Sandbox Analysis ---
    needs_viz = bool(section.get("requires_visualization", True))
    rows = _load_report_rows(report_section)
    analysis = get_visualization_service().generate_grounded_report_analysis(
        data_rows=rows,
        user_query=section.get("analysis_query", ""),
        section_title=title,
    )

    if not analysis.success:
        report_section["status"] = "failed"
        report_section["analysis_status"] = "failed"
        report_section["error"] = analysis.error or "Grounded analysis failed"
        report_section["sandbox_analysis"] = {
            "success": False,
            "error": analysis.error,
        }
        report_section["insight_markdown"] = (
            f"Không thể phân tích dữ liệu: {analysis.error}"
        )
        report_section["insight_citations"] = []
        report_section["limitations"] = [str(analysis.error)]
        return {"_report_sections_raw": [report_section]}

    report_section["sandbox_analysis"] = {
        "success": True,
        "execution_time_ms": analysis.execution_time_ms,
        "code_executed": analysis.code_executed,
    }
    report_section["computed_stats"] = analysis.computed_stats
    report_section["chart_manifest"] = analysis.chart_manifest
    thread_id = state.get("thread_id", "default")
    conversation_turn = state.get("conversation_turn", 0)
    image_data = analysis.image_data if needs_viz else None
    report_section["chart_html"] = analysis.chart_html if needs_viz else None
    # Save chart image to file, store URL reference in state
    chart_url = None
    if image_data:
        section_id = report_section.get("section_id", "unknown")
        rel_path = save_section_chart_to_file(
            image_data=image_data,
            section_id=section_id,
            image_format=analysis.image_format or "png",
            thread_id=thread_id,
            turn_number=conversation_turn,
        )
        if rel_path:
            chart_url = chart_url_from_path(rel_path)
    report_section["chart_image_url"] = chart_url
    report_section["chart_image_format"] = analysis.image_format if needs_viz else None
    report_section["analysis_status"] = "done"
    report_section["visualization"] = {
        "success": bool(chart_url),
        "image_url": chart_url,
        "image_format": analysis.image_format,
        "image_size_bytes": len(image_data) if image_data else 0,
        "execution_time_ms": analysis.execution_time_ms,
        "error": analysis.error,
    }
    report_section = _validate_section_semantics(report_section)

    # --- Step 3: Insight Generation ---
    settings = load_settings()
    messages = _build_report_insight_messages(state, report_section)
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
        if insight_markdown:
            report_section["insight_markdown"] = insight_markdown
            report_section["insight_citations"] = (
                citations if isinstance(citations, list) else []
            )
            report_section["limitations"] = (
                limitations if isinstance(limitations, list) else []
            )
            report_section = _apply_semantic_caveat(report_section, state)
        else:
            report_section = _fallback_section_insight(report_section)
            report_section = _apply_semantic_caveat(report_section, state)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Report insight generation failed for section {id}: {error}",
            id=section_id,
            error=str(exc),
        )
        report_section = _fallback_section_insight(report_section)
        report_section = _apply_semantic_caveat(report_section, state)

    return {"_report_sections_raw": [report_section]}


# ---------------------------------------------------------------------------
# NODE 5: Sections Sort — collect fan-in results, sort by section_order
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
# NODE 6: Writer
# ---------------------------------------------------------------------------


def _section_writer_payload(section: ReportSection) -> dict[str, Any]:
    return {
        "section_id": section.get("section_id"),
        "title": section.get("title"),
        "analysis_query": section.get("analysis_query"),
        "analysis_type": section.get("analysis_type", "descriptive"),
        "status": section.get("status"),
        "analysis_status": section.get("analysis_status"),
        "section_confidence": section.get("section_confidence", "medium"),
        "insight_markdown": _truncate_text(section.get("insight_markdown", ""), 3000),
        "citations": section.get("insight_citations", []),
        "computed_stats": _writer_stats_payload(section),
        "semantic_warnings": section.get("semantic_warnings", []),
        "limitations": section.get("limitations", []),
    }


def report_writer_node(state: AgentState) -> AgentState:
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
        query=state.get("report_request") or state.get("user_query", ""),
        report_plan=report_plan,
        section_results=section_results,
        critic_feedback=state.get("critic_feedback", ""),
        domain_context=(state.get("report_data_profile") or {}).get(
            "domain_summary", ""
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
        lines = [f"# {state.get('report_plan', {}).get('title', 'Report')}"]
        for section in state.get("report_sections", []):
            lines.append(f"## {section.get('title', 'Section')}")
            if section.get("status") == "failed":
                lines.append(
                    f"Mục này thất bại: {section.get('error', 'Unknown error')}"
                )
            else:
                lines.append(
                    section.get("insight_markdown", "Không có insight cho mục này.")
                )
        report_draft = "\n\n".join(lines)

    report_draft = _cleanup_report_markdown(report_draft)
    report_draft = _ensure_report_recommendations(report_draft, state)

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


# ---------------------------------------------------------------------------
# NODE 7: Critic
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
        "status": section.get("status"),
        "analysis_type": section.get("analysis_type", "descriptive"),
        "section_confidence": section.get("section_confidence", "medium"),
        "insight_markdown": _truncate_text(section.get("insight_markdown", ""), 3000),
        "citations": section.get("insight_citations", []),
        "computed_stats": stats,
        "semantic_warnings": section.get("semantic_warnings", []),
        "limitations": section.get("limitations", []),
    }


def report_critic_node(state: AgentState) -> AgentState:
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
        "critic_verdict": verdict,
        "critic_issues": issues,
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
    return (
        "report_writer"
        if state.get("critic_decision") == "revise"
        else "report_finalize"
    )


# ---------------------------------------------------------------------------
# NODE 8: Finalize — save report.md to disk and package output
# ---------------------------------------------------------------------------


def report_finalize_node(state: AgentState) -> AgentState:
    critic_verdict = str(state.get("critic_verdict", "APPROVED")).upper()
    used_safe_fallback = critic_verdict == "REVISE"
    if used_safe_fallback:
        report_markdown = _build_safe_report_markdown(state)
    else:
        report_markdown = _cleanup_report_markdown(state.get("report_draft", ""))
    plan_title = state.get("report_plan", {}).get("title", "Report")
    errors = state.get("errors", [])
    answer = "Đây là report của bạn. Bấm vào nút Report để xem bản trình bày đầy đủ."
    confidence, confidence_rationale = _derive_report_confidence(
        state, used_safe_fallback=used_safe_fallback
    )

    # Save report markdown to disk
    report_dir = Path("reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "report.md"
    try:
        report_path.write_text(
            report_markdown or f"# {plan_title}\n\nNo report content was generated.",
            encoding="utf-8",
        )
        logger.info("Report saved to {path}", path=report_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to save report.md: {error}", error=str(exc))

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
            "context_chunks=0",
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
        "result_metadata": None,
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


# ---------------------------------------------------------------------------
# Graph Construction
# ---------------------------------------------------------------------------


def build_report_subgraph():
    """Build the report subgraph with Send()-based per-section pipeline.

    Flow:
        START
          → profiler_sampler (SQL: 100 random rows + column stats)
          → profiler_analyzer (LLM: domain context + suggested sections)
          → report_planner (plan → _report_sections_planned)
          → [fan_out_sections] ──Send()──→ section_pipeline (per-section: SQL → sandbox → insight)
          → sections_sort (fan-in: collect + sort)
          → report_writer
          → report_critic ──conditional──→ report_writer (revise) | report_finalize
          → END
    """
    builder = StateGraph(AgentState)

    builder.add_node(
        "profiler_sampler",
        _instrument_node("profiler_sampler_node", profiler_sampler_node),
    )
    builder.add_node(
        "profiler_analyzer",
        _instrument_node("profiler_analyzer_node", profiler_analyzer_node),
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
        "report_writer",
        _instrument_node("report_writer_node", report_writer_node),
    )
    builder.add_node(
        "report_critic",
        _instrument_node("report_critic_node", report_critic_node),
    )
    builder.add_node(
        "report_finalize",
        _instrument_node("report_finalize_node", report_finalize_node),
    )

    # Edges
    builder.add_edge(START, "profiler_sampler")
    builder.add_edge("profiler_sampler", "profiler_analyzer")
    builder.add_edge("profiler_analyzer", "report_planner")

    # Send() fan-out: planner → N × section_pipeline (parallel)
    builder.add_conditional_edges(
        "report_planner",
        fan_out_sections,
        ["section_pipeline"],
    )

    # Fan-in: all section_pipeline instances → sections_sort
    builder.add_edge("section_pipeline", "sections_sort")

    builder.add_edge("sections_sort", "report_writer")
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
