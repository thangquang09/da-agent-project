from __future__ import annotations

import re
from typing import Any


def _has_heading(report_markdown: str, *titles: str) -> bool:
    pattern = r"^##\s+(" + "|".join(re.escape(title) for title in titles) + r")\b"
    return bool(re.search(pattern, report_markdown, flags=re.IGNORECASE | re.MULTILINE))


def validate_report_coverage(
    coverage_summary: dict[str, Any] | None,
    unresolved_items: list[dict[str, Any]] | None,
    report_markdown: str,
) -> list[str]:
    coverage_summary = coverage_summary or {}
    unresolved_items = unresolved_items or []
    issues: list[str] = []

    dropped = coverage_summary.get("dropped_must_question_ids") or []
    if dropped:
        issues.append(
            "Planner coverage is incomplete: at least one must-answer user question was not mapped or explained."
        )

    if unresolved_items and not _has_heading(
        report_markdown,
        "Questions Requiring Follow-up",
        "Câu hỏi cần làm rõ thêm",
    ):
        issues.append(
            "Draft is missing the required follow-up questions section for unresolved user asks."
        )
    return issues


def validate_claim_grounding(
    report_sections: list[dict[str, Any]] | None,
    report_markdown: str,
) -> list[str]:
    report_sections = report_sections or []
    issues: list[str] = []
    all_claims = [
        claim
        for section in report_sections
        for claim in section.get("claims", []) or []
        if isinstance(claim, dict)
    ]
    if not all_claims and report_sections:
        issues.append("Report sections are missing structured claim packets.")

    for claim in all_claims:
        if not claim.get("evidence_refs"):
            issues.append("At least one claim packet is missing evidence references.")
            break

    allowed_refs = {
        str(ref).strip()
        for section in report_sections
        for packet in section.get("evidence_packets", []) or []
        for ref in packet.get("evidence_paths", []) or []
        if str(ref).strip()
    }
    for claim in all_claims:
        refs = [
            str(ref).strip()
            for ref in claim.get("evidence_refs", [])
            if str(ref).strip()
        ]
        if refs and any(ref not in allowed_refs for ref in refs):
            issues.append(
                "At least one claim packet cites evidence references that do not exist in the section evidence packets."
            )
            break

    if _has_heading(report_markdown, "Recommendations", "Khuyến nghị"):
        ready_claims = [
            claim for claim in all_claims if claim.get("recommendation_ready")
        ]
        if not ready_claims and all_claims:
            issues.append(
                "Draft recommendations are present but no supported claim was marked recommendation-ready."
            )
    return issues


def validate_interpretation_strength(
    report_sections: list[dict[str, Any]] | None,
    report_markdown: str,
) -> list[str]:
    report_sections = report_sections or []
    issues: list[str] = []
    lower_draft = report_markdown.lower()
    strong_markers = [
        "chứng minh rằng",
        "nguyên nhân là",
        "do đó chắc chắn",
        "cho thấy chính sách",
        "cần triển khai ngay",
        "yếu tố quyết định",
        "decisive factor",
        "proves",
    ]
    caveat_markers = [
        "giả thuyết",
        "hypothesis",
        "thận trọng",
        "caveat",
        "không chứng minh",
        "descriptive",
    ]
    if any(marker in lower_draft for marker in strong_markers) and not any(
        marker in lower_draft for marker in caveat_markers
    ):
        if any(section.get("semantic_warnings") for section in report_sections):
            issues.append(
                "Draft makes strong analytical claims without preserving caveats from semantically weak or warning-heavy sections."
            )
    return issues


def validate_report_structure(
    report_markdown: str,
    report_sections: list[dict[str, Any]] | None,
) -> list[str]:
    report_sections = report_sections or []
    issues: list[str] = []
    if not re.search(r"^#\s+.+", report_markdown, flags=re.MULTILINE):
        issues.append("Draft is missing a top-level H1 title.")
    if not _has_heading(
        report_markdown,
        "Executive Summary",
        "Tóm tắt điều hành",
        "Tóm tắt tổng quan",
    ):
        issues.append("Draft is missing the required executive summary section.")
    if not _has_heading(report_markdown, "Conclusion", "Kết luận"):
        issues.append("Draft is missing the required conclusion section.")
    if not _has_heading(report_markdown, "Recommendations", "Khuyến nghị"):
        issues.append("Draft is missing the required recommendations section.")
    missing_section_titles = [
        section.get("title", "")
        for section in report_sections
        if section.get("status") == "done"
        and section.get("title")
        and f"## {section.get('title')}" not in report_markdown
    ]
    if missing_section_titles:
        issues.append(
            "Draft is missing one or more planned section bodies: "
            + ", ".join(missing_section_titles[:5])
        )
    return issues


def validate_section_warning_quality(
    report_sections: list[dict[str, Any]] | None,
) -> list[str]:
    report_sections = report_sections or []
    issues: list[str] = []
    for section in report_sections:
        for packet in section.get("evidence_packets", []) or []:
            warnings = [
                str(item).strip().lower()
                for item in packet.get("quality_warnings", []) or []
                if str(item).strip()
            ]
            underlying = packet.get("underlying_observation_count")
            if underlying is None:
                continue
            if underlying >= 5 and any("small sample" in item for item in warnings):
                issues.append(
                    "A section reports a small-sample warning even though the underlying observation count is not small."
                )
                return issues
    return issues


def run_report_validators(
    coverage_summary: dict[str, Any] | None,
    unresolved_items: list[dict[str, Any]] | None,
    report_sections: list[dict[str, Any]] | None,
    report_markdown: str,
) -> list[str]:
    issues: list[str] = []
    for validator in (
        lambda: validate_report_coverage(
            coverage_summary, unresolved_items, report_markdown
        ),
        lambda: validate_claim_grounding(report_sections, report_markdown),
        lambda: validate_interpretation_strength(report_sections, report_markdown),
        lambda: validate_report_structure(report_markdown, report_sections),
        lambda: validate_section_warning_quality(report_sections),
    ):
        for issue in validator():
            if issue not in issues:
                issues.append(issue)
    return issues
