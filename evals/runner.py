from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import load_settings
from app.main import run_query
from app.tools import query_sql, validate_sql
from evals.case_contracts import EvalCase, load_cases_jsonl


GATE_THRESHOLDS = {
    "routing_accuracy": 0.90,
    "sql_validity_rate": 0.90,
    "tool_path_accuracy": 0.95,
    "answer_format_validity": 1.00,
}


@dataclass
class CaseResult:
    case_id: str
    suite: str
    language: str
    query: str
    expected_intent: str
    predicted_intent: str
    routing_correct: bool
    expected_tools: list[str]
    used_tools: list[str]
    tool_path_correct: bool
    should_have_sql: bool
    generated_sql: str
    has_sql: bool
    sql_valid: bool
    answer_format_valid: bool
    confidence: str
    latency_ms: float
    execution_match: bool | None
    error_categories: list[str]
    failure_bucket: str | None
    run_id: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


def _required_payload_keys_present(payload: dict[str, Any]) -> bool:
    required = {"answer", "evidence", "confidence", "used_tools", "generated_sql"}
    if not required.issubset(set(payload.keys())):
        return False
    if not isinstance(payload.get("evidence"), list):
        return False
    if not isinstance(payload.get("used_tools"), list):
        return False
    return True


def _extract_intent(payload: dict[str, Any]) -> str:
    if payload.get("intent"):
        return str(payload["intent"])
    for item in payload.get("evidence", []):
        text = str(item)
        if text.startswith("intent="):
            return text.split("=", 1)[1]
    return "unknown"


def _tool_path_ok(expected_tools: list[str], used_tools: list[str]) -> bool:
    used = set(used_tools)
    return all(tool in used for tool in expected_tools)


def _sql_validity(sql: str, db_path: str | None) -> bool:
    if not sql:
        return False
    if not db_path:
        return False
    result = validate_sql(sql, db_path=Path(db_path))
    return result.is_valid


def _normalize_rows(rows: list[dict[str, Any]], limit: int = 100) -> list[tuple]:
    compact = rows[:limit]
    normalized: list[tuple] = []
    for row in compact:
        items = tuple(sorted((str(k), str(v)) for k, v in row.items()))
        normalized.append(items)
    normalized.sort()
    return normalized


def _execution_match(gold_sql: str | None, pred_sql: str, db_path: str | None) -> bool | None:
    if not gold_sql or not pred_sql or not db_path:
        return None
    try:
        gold_result = query_sql(gold_sql, db_path=Path(db_path))
        pred_result = query_sql(pred_sql, db_path=Path(db_path))
    except Exception:
        return False

    if gold_result.get("columns") != pred_result.get("columns"):
        return False
    return _normalize_rows(gold_result.get("rows", [])) == _normalize_rows(pred_result.get("rows", []))


def _failure_bucket(case_result: CaseResult) -> str | None:
    if not case_result.routing_correct:
        return "ROUTING_ERROR"
    if not case_result.answer_format_valid:
        return "SYNTHESIS_ERROR"
    if case_result.should_have_sql and not case_result.has_sql:
        return "SQL_GENERATION_ERROR"
    if case_result.should_have_sql and case_result.has_sql and not case_result.sql_valid:
        return "SQL_VALIDATION_ERROR"
    if case_result.execution_match is False:
        return "SQL_EXECUTION_ERROR"
    if not case_result.tool_path_correct:
        return "TOOL_PATH_MISMATCH"
    return None


def run_case(case: EvalCase, recursion_limit: int) -> CaseResult:
    start = time.perf_counter()
    payload = run_query(
        case.query,
        recursion_limit=recursion_limit,
        db_path=case.target_db_path,
    )
    latency_ms = round((time.perf_counter() - start) * 1000, 2)

    predicted_intent = _extract_intent(payload)
    used_tools = [str(item) for item in payload.get("used_tools", [])]
    generated_sql = str(payload.get("generated_sql", "") or "")
    has_sql = bool(generated_sql.strip())
    sql_valid = _sql_validity(generated_sql, case.target_db_path) if case.should_have_sql else True
    execution_match = _execution_match(case.gold_sql, generated_sql, case.target_db_path)

    result = CaseResult(
        case_id=case.id,
        suite=case.suite,
        language=case.language,
        query=case.query,
        expected_intent=case.expected_intent,
        predicted_intent=predicted_intent,
        routing_correct=(predicted_intent == case.expected_intent),
        expected_tools=case.expected_tools,
        used_tools=used_tools,
        tool_path_correct=_tool_path_ok(case.expected_tools, used_tools),
        should_have_sql=case.should_have_sql,
        generated_sql=generated_sql,
        has_sql=has_sql,
        sql_valid=sql_valid,
        answer_format_valid=_required_payload_keys_present(payload),
        confidence=str(payload.get("confidence", "unknown")),
        latency_ms=latency_ms,
        execution_match=execution_match,
        error_categories=[str(item) for item in payload.get("error_categories", [])],
        failure_bucket=None,
        run_id=str(payload.get("run_id", "")),
    )
    result.failure_bucket = _failure_bucket(result)
    return result


def _metric_ratio(results: list[CaseResult], attr: str) -> float:
    if not results:
        return 0.0
    return round(sum(1 for item in results if bool(getattr(item, attr))) / len(results), 4)


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    by_suite: dict[str, list[CaseResult]] = defaultdict(list)
    by_language: dict[str, list[CaseResult]] = defaultdict(list)
    for item in results:
        by_suite[item.suite].append(item)
        by_language[item.language].append(item)

    failure_counts = Counter(item.failure_bucket for item in results if item.failure_bucket)
    spider_results = [item for item in results if item.suite == "spider" and item.execution_match is not None]

    def pack(group: list[CaseResult]) -> dict[str, Any]:
        return {
            "count": len(group),
            "routing_accuracy": _metric_ratio(group, "routing_correct"),
            "tool_path_accuracy": _metric_ratio(group, "tool_path_correct"),
            "sql_validity_rate": _metric_ratio(group, "sql_valid"),
            "answer_format_validity": _metric_ratio(group, "answer_format_valid"),
            "avg_latency_ms": round(sum(item.latency_ms for item in group) / max(len(group), 1), 2),
        }

    summary = {
        "total_cases": len(results),
        "overall": pack(results),
        "by_suite": {suite: pack(group) for suite, group in by_suite.items()},
        "by_language": {lang: pack(group) for lang, group in by_language.items()},
        "spider_execution_match_rate": round(
            sum(1 for item in spider_results if item.execution_match) / max(len(spider_results), 1),
            4,
        )
        if spider_results
        else None,
        "failure_buckets": dict(failure_counts),
    }
    return summary


def _pass_gate(summary: dict[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    overall = summary.get("overall", {})
    for metric, threshold in GATE_THRESHOLDS.items():
        value = float(overall.get(metric, 0.0))
        if value < threshold:
            failures.append(f"{metric}={value:.4f} < {threshold:.2f}")
    return (len(failures) == 0, failures)


def _render_markdown(summary: dict[str, Any], per_case_path: Path) -> str:
    lines = [
        "# Eval Report",
        "",
        f"- Total cases: {summary['total_cases']}",
        f"- Routing accuracy: {summary['overall']['routing_accuracy']}",
        f"- Tool-path accuracy: {summary['overall']['tool_path_accuracy']}",
        f"- SQL validity rate: {summary['overall']['sql_validity_rate']}",
        f"- Answer format validity: {summary['overall']['answer_format_validity']}",
        f"- Average latency (ms): {summary['overall']['avg_latency_ms']}",
        f"- Spider execution match: {summary.get('spider_execution_match_rate')}",
        "",
        "## By Suite",
    ]
    for suite, stats in summary.get("by_suite", {}).items():
        lines.extend(
            [
                f"### {suite}",
                f"- count: {stats['count']}",
                f"- routing_accuracy: {stats['routing_accuracy']}",
                f"- tool_path_accuracy: {stats['tool_path_accuracy']}",
                f"- sql_validity_rate: {stats['sql_validity_rate']}",
                f"- answer_format_validity: {stats['answer_format_validity']}",
                f"- avg_latency_ms: {stats['avg_latency_ms']}",
                "",
            ]
        )
    lines.append("## Failure Buckets")
    for bucket, count in summary.get("failure_buckets", {}).items():
        lines.append(f"- {bucket}: {count}")
    lines.extend(["", f"Per-case JSONL: `{per_case_path}`", ""])
    return "\n".join(lines)


def _load_suite_cases(cases_dir: Path, suite: str) -> list[EvalCase]:
    cases: list[EvalCase] = []
    if suite in {"all", "domain"}:
        cases.extend(load_cases_jsonl(cases_dir / "domain_cases.jsonl"))
    if suite in {"all", "spider"}:
        cases.extend(load_cases_jsonl(cases_dir / "spider_cases.jsonl"))
    return cases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run dataset-driven evaluation")
    parser.add_argument("--cases-dir", default="evals/cases")
    parser.add_argument("--output-dir", default="evals/reports")
    parser.add_argument("--suite", choices=["all", "domain", "spider"], default="all")
    parser.add_argument("--recursion-limit", type=int, default=25)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--enforce-gates", action="store_true")
    parser.add_argument(
        "--enable-llm-sql-generation",
        action="store_true",
        help="Enable LLM SQL generation during eval run",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.enable_llm_sql_generation:
        os.environ["ENABLE_LLM_SQL_GENERATION"] = "true"
        load_settings.cache_clear()

    cases_dir = Path(args.cases_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cases = _load_suite_cases(cases_dir=cases_dir, suite=args.suite)
    if args.limit and args.limit > 0:
        cases = cases[: args.limit]
    if not cases:
        raise RuntimeError(f"No eval cases found under {cases_dir}")

    results = [run_case(case, recursion_limit=args.recursion_limit) for case in cases]
    summary = summarize(results)

    per_case_path = output_dir / "per_case.jsonl"
    with per_case_path.open("w", encoding="utf-8") as handle:
        for item in results:
            handle.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")

    summary_json_path = output_dir / "latest_summary.json"
    summary_json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    summary_md_path = output_dir / "latest_summary.md"
    summary_md_path.write_text(_render_markdown(summary, per_case_path), encoding="utf-8")

    passed, failures = _pass_gate(summary)
    print(f"Wrote: {summary_json_path}")
    print(f"Wrote: {summary_md_path}")
    print(f"Wrote: {per_case_path}")
    print(f"Gates passed: {passed}")
    if failures:
        print("Gate failures:")
        for line in failures:
            print(f"- {line}")
    if args.enforce_gates and not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
