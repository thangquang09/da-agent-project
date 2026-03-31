from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import load_settings
from app.main import run_query
from app.tools import query_sql, validate_sql
from evals.case_contracts import EvalCase, load_cases_jsonl
from evals.groundedness import evaluate_groundedness
from evals.metrics import (
    ExecutionAccuracyEvaluator,
    LLMAnswerJudge,
    SpiderExactMatchEvaluator,
)


GATE_THRESHOLDS = {
    "routing_accuracy": 0.90,
    "sql_validity_rate": 0.90,
    "tool_path_accuracy": 0.95,
    "answer_format_validity": 1.00,
    "groundedness_pass_rate": 0.70,
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
    spider_exact_match: bool | None
    spider_exact_match_f1: float | None
    answer_quality_score: float | None
    answer_quality_reasoning: str | None
    groundedness_score: float
    groundedness_pass: bool
    unsupported_claims: list[str]
    groundedness_fail_reasons: list[str]
    marked_answer: str
    error_categories: list[str]
    failure_bucket: str | None
    run_id: str
    expected_context_type: str = "default"
    predicted_context_type: str | None = None
    context_type_correct: bool | None = None

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


def _execution_match(
    gold_sql: str | None, pred_sql: str, db_path: str | None
) -> bool | None:
    if not gold_sql or not pred_sql or not db_path:
        return None
    try:
        gold_result = query_sql(gold_sql, db_path=Path(db_path))
        pred_result = query_sql(pred_sql, db_path=Path(db_path))
    except Exception:
        return False

    if gold_result.get("columns") != pred_result.get("columns"):
        return False
    return _normalize_rows(gold_result.get("rows", [])) == _normalize_rows(
        pred_result.get("rows", [])
    )


def _failure_bucket(case_result: CaseResult) -> str | None:
    if not case_result.routing_correct:
        return "ROUTING_ERROR"
    if not case_result.answer_format_valid:
        return "SYNTHESIS_ERROR"
    if case_result.should_have_sql and not case_result.has_sql:
        return "SQL_GENERATION_ERROR"
    if (
        case_result.should_have_sql
        and case_result.has_sql
        and not case_result.sql_valid
    ):
        return "SQL_VALIDATION_ERROR"
    if case_result.execution_match is False:
        return "SQL_EXECUTION_ERROR"
    if case_result.spider_exact_match is False:
        return "SQL_COMPONENT_MISMATCH"
    if not case_result.groundedness_pass:
        return "HALLUCINATION_RISK"
    if not case_result.tool_path_correct:
        return "TOOL_PATH_MISMATCH"
    return None


def run_case(case: EvalCase, recursion_limit: int) -> CaseResult:
    spider_exact_match_evaluator = SpiderExactMatchEvaluator()
    execution_evaluator = ExecutionAccuracyEvaluator()
    answer_judge = LLMAnswerJudge()

    start = time.perf_counter()
    payload = run_query(
        case.query,
        recursion_limit=recursion_limit,
        db_path=case.target_db_path,
        expected_keywords=case.expected_keywords if case.expected_keywords else None,
    )
    latency_ms = round((time.perf_counter() - start) * 1000, 2)

    predicted_intent = _extract_intent(payload)
    used_tools = [str(item) for item in payload.get("used_tools", [])]
    generated_sql = str(payload.get("generated_sql", "") or "")
    has_sql = bool(generated_sql.strip())
    sql_valid = (
        _sql_validity(generated_sql, case.target_db_path)
        if case.should_have_sql
        else True
    )

    spider_exact_match_result = None
    spider_exact_match_f1 = None
    if case.gold_sql and generated_sql:
        spider_exact_match_result = spider_exact_match_evaluator.evaluate(
            generated_sql, case.gold_sql, case.target_db_path
        )
        spider_exact_match_f1 = spider_exact_match_result.overall_f1

    execution_match = None
    if case.gold_sql and generated_sql:
        exec_result = execution_evaluator.evaluate(
            generated_sql, case.gold_sql, case.target_db_path
        )
        execution_match = exec_result.execution_match

    answer_quality_score = None
    answer_quality_reasoning = None
    if payload.get("answer"):
        answer_judge_result = answer_judge.evaluate(
            question=case.query,
            answer=str(payload.get("answer", "")),
            evidence=[str(item) for item in payload.get("evidence", [])],
        )
        answer_quality_score = answer_judge_result.overall_score
        answer_quality_reasoning = answer_judge_result.reasoning

    groundedness = evaluate_groundedness(
        answer=str(payload.get("answer", "")),
        evidence=[str(item) for item in payload.get("evidence", [])],
        expected_keywords=case.expected_keywords,
    )
    payload_unsupported_claims = [
        str(item) for item in payload.get("unsupported_claims", [])
    ]
    merged_unsupported_claims = sorted(
        set(payload_unsupported_claims + groundedness.unsupported_claims)
    )
    merged_fail_reasons = list(groundedness.fail_reasons)
    if payload_unsupported_claims:
        merged_fail_reasons.append("payload_unsupported_claims_present")

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
        spider_exact_match=spider_exact_match_result.exact_match
        if spider_exact_match_result
        else None,
        spider_exact_match_f1=spider_exact_match_f1,
        answer_quality_score=answer_quality_score,
        answer_quality_reasoning=answer_quality_reasoning,
        groundedness_score=groundedness.score,
        groundedness_pass=groundedness.passed and not merged_unsupported_claims,
        unsupported_claims=merged_unsupported_claims,
        groundedness_fail_reasons=merged_fail_reasons,
        marked_answer=groundedness.marked_answer,
        error_categories=[str(item) for item in payload.get("error_categories", [])],
        failure_bucket=None,
        run_id=str(payload.get("run_id", "")),
        expected_context_type=case.expected_context_type,
        predicted_context_type=str(payload.get("context_type")),
        context_type_correct=(
            str(payload.get("context_type")) == case.expected_context_type
        )
        if payload.get("context_type")
        else None,
    )
    result.failure_bucket = _failure_bucket(result)
    return result


def _metric_ratio(results: list[CaseResult], attr: str) -> float:
    if not results:
        return 0.0
    return round(
        sum(1 for item in results if bool(getattr(item, attr))) / len(results), 4
    )


def _context_type_accuracy(results: list[CaseResult]) -> float | None:
    valid = [item for item in results if item.context_type_correct is not None]
    if not valid:
        return None
    return round(sum(1 for item in valid if item.context_type_correct) / len(valid), 4)


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    by_suite: dict[str, list[CaseResult]] = defaultdict(list)
    by_language: dict[str, list[CaseResult]] = defaultdict(list)
    for item in results:
        by_suite[item.suite].append(item)
        by_language[item.language].append(item)

    failure_counts = Counter(
        item.failure_bucket for item in results if item.failure_bucket
    )
    spider_results = [
        item
        for item in results
        if item.suite == "spider" and item.execution_match is not None
    ]
    spider_exact_match_results = [
        item
        for item in results
        if item.suite == "spider" and item.spider_exact_match is not None
    ]

    def pack(group: list[CaseResult]) -> dict[str, Any]:
        exact_match_vals = [
            item.spider_exact_match
            for item in group
            if item.spider_exact_match is not None
        ]
        exact_match_f1_vals = [
            item.spider_exact_match_f1
            for item in group
            if item.spider_exact_match_f1 is not None
        ]
        answer_quality_vals = [
            item.answer_quality_score
            for item in group
            if item.answer_quality_score is not None
        ]
        context_type_vals = [
            item.context_type_correct
            for item in group
            if item.context_type_correct is not None
        ]
        return {
            "count": len(group),
            "routing_accuracy": _metric_ratio(group, "routing_correct"),
            "tool_path_accuracy": _metric_ratio(group, "tool_path_correct"),
            "sql_validity_rate": _metric_ratio(group, "sql_valid"),
            "answer_format_validity": _metric_ratio(group, "answer_format_valid"),
            "groundedness_pass_rate": _metric_ratio(group, "groundedness_pass"),
            "context_type_accuracy": round(
                sum(1 for v in context_type_vals if v) / max(len(context_type_vals), 1),
                4,
            )
            if context_type_vals
            else None,
            "avg_groundedness_score": round(
                sum(item.groundedness_score for item in group) / max(len(group), 1), 4
            ),
            "avg_latency_ms": round(
                sum(item.latency_ms for item in group) / max(len(group), 1), 2
            ),
            "spider_exact_match_rate": round(
                sum(1 for v in exact_match_vals if v) / max(len(exact_match_vals), 1), 4
            )
            if exact_match_vals
            else None,
            "spider_exact_match_avg_f1": round(
                sum(exact_match_f1_vals) / max(len(exact_match_f1_vals), 1), 4
            )
            if exact_match_f1_vals
            else None,
            "avg_answer_quality_score": round(
                sum(answer_quality_vals) / max(len(answer_quality_vals), 1), 4
            )
            if answer_quality_vals
            else None,
        }

    summary = {
        "total_cases": len(results),
        "overall": pack(results),
        "by_suite": {suite: pack(group) for suite, group in by_suite.items()},
        "by_language": {lang: pack(group) for lang, group in by_language.items()},
        "spider_execution_match_rate": round(
            sum(1 for item in spider_results if item.execution_match)
            / max(len(spider_results), 1),
            4,
        )
        if spider_results
        else None,
        "spider_exact_match_rate": round(
            sum(1 for item in spider_exact_match_results if item.spider_exact_match)
            / max(len(spider_exact_match_results), 1),
            4,
        )
        if spider_exact_match_results
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
        f"- Groundedness pass rate: {summary['overall']['groundedness_pass_rate']}",
        f"- Context type accuracy: {summary['overall'].get('context_type_accuracy')}",
        f"- Average groundedness score: {summary['overall']['avg_groundedness_score']}",
        f"- Average latency (ms): {summary['overall']['avg_latency_ms']}",
        f"- Spider execution match: {summary.get('spider_execution_match_rate')}",
        f"- Spider exact set match: {summary.get('spider_exact_match_rate')}",
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
                f"- groundedness_pass_rate: {stats['groundedness_pass_rate']}",
                f"- context_type_accuracy: {stats.get('context_type_accuracy')}",
                f"- avg_groundedness_score: {stats['avg_groundedness_score']}",
                f"- avg_latency_ms: {stats['avg_latency_ms']}",
                f"- spider_exact_match_rate: {stats.get('spider_exact_match_rate')}",
                f"- spider_exact_match_avg_f1: {stats.get('spider_exact_match_avg_f1')}",
                f"- avg_answer_quality_score: {stats.get('avg_answer_quality_score')}",
                "",
            ]
        )
    lines.append("## Failure Buckets")
    for bucket, count in summary.get("failure_buckets", {}).items():
        lines.append(f"- {bucket}: {count}")
    lines.extend(["", f"Per-case JSONL: `{per_case_path}`", ""])
    return "\n".join(lines)


def _load_suite_cases(
    cases_dir: Path, suite: str, split: str = "dev"
) -> list[EvalCase]:
    cases: list[EvalCase] = []
    if suite in {"all", "domain"}:
        cases.extend(load_cases_jsonl(cases_dir / "domain_cases.jsonl"))
    if suite in {"all", "spider"}:
        if split in {"dev", "all"}:
            cases.extend(load_cases_jsonl(cases_dir / "dev" / "spider_dev.jsonl"))
        if split in {"test", "all"}:
            cases.extend(load_cases_jsonl(cases_dir / "test" / "spider_test.jsonl"))
    if suite in {"all", "movielens"}:
        for lang in ["en", "vi"]:
            if split in {"dev", "all"}:
                cases.extend(
                    load_cases_jsonl(cases_dir / "dev" / f"movielens_{lang}_dev.jsonl")
                )
            if split in {"test", "all"}:
                cases.extend(
                    load_cases_jsonl(
                        cases_dir / "test" / f"movielens_{lang}_test.jsonl"
                    )
                )
    return cases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run dataset-driven evaluation")
    parser.add_argument("--cases-dir", default="evals/cases")
    parser.add_argument("--output-dir", default="evals/reports")
    parser.add_argument(
        "--suite", choices=["all", "domain", "spider", "movielens"], default="all"
    )
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    parser.add_argument("--recursion-limit", type=int, default=25)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--enforce-gates", action="store_true")
    parser.add_argument(
        "--enable-llm-sql-generation",
        action="store_true",
        help="Enable LLM SQL generation during eval run",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers for eval execution (default: 4)",
    )
    parser.add_argument(
        "--tag",
        type=str,
        default=None,
        help="Custom tag for output files (e.g., 'debug', 'baseline')",
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

    cases = _load_suite_cases(cases_dir=cases_dir, suite=args.suite, split=args.split)
    if args.limit and args.limit > 0:
        cases = cases[: args.limit]
    if not cases:
        raise RuntimeError(f"No eval cases found under {cases_dir}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suite_tag = args.suite
    if args.tag:
        suite_tag = f"{args.suite}_{args.tag}"
    run_prefix = f"{suite_tag}_{args.split}_{timestamp}"

    def run_with_args(case: EvalCase) -> CaseResult:
        return run_case(case, recursion_limit=args.recursion_limit)

    start_time = time.time()
    if args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(run_with_args, case): case for case in cases}
            results = []
            for future in as_completed(futures):
                results.append(future.result())
    else:
        results = [
            run_case(case, recursion_limit=args.recursion_limit) for case in cases
        ]
    elapsed = time.time() - start_time

    summary = summarize(results)

    per_case_path = output_dir / f"per_case_{run_prefix}.jsonl"
    with per_case_path.open("w", encoding="utf-8") as handle:
        for item in results:
            handle.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")

    summary_json_path = output_dir / f"summary_{run_prefix}.json"
    summary_json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summary_md_path = output_dir / f"summary_{run_prefix}.md"
    summary_md_path.write_text(
        _render_markdown(summary, per_case_path), encoding="utf-8"
    )

    latest_json_path = output_dir / "latest_summary.json"
    latest_json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    latest_md_path = output_dir / "latest_summary.md"
    latest_md_path.write_text(
        _render_markdown(summary, per_case_path), encoding="utf-8"
    )

    passed, failures = _pass_gate(summary)
    print(
        f"Completed {len(results)} cases in {elapsed:.1f}s ({elapsed / len(results):.1f}s per case)"
    )
    print(f"Wrote: {summary_json_path}")
    print(f"Wrote: {summary_md_path}")
    print(f"Wrote: {per_case_path}")
    print(f"Updated: {latest_json_path}")
    print(f"Updated: {latest_md_path}")
    print(f"Gates passed: {passed}")
    if failures:
        print("Gate failures:")
        for line in failures:
            print(f"- {line}")
    if args.enforce_gates and not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
