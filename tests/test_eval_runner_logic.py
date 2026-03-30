from __future__ import annotations

from evals.runner import CaseResult, _failure_bucket, _pass_gate, _required_payload_keys_present, summarize


def test_required_payload_keys_present():
    payload = {
        "answer": "ok",
        "evidence": ["intent=sql"],
        "confidence": "high",
        "used_tools": ["route_intent"],
        "generated_sql": "SELECT 1",
    }
    assert _required_payload_keys_present(payload) is True
    assert _required_payload_keys_present({"answer": "missing"}) is False


def test_failure_bucket_prefers_routing_error():
    item = CaseResult(
        case_id="c1",
        suite="domain",
        language="vi",
        query="q",
        expected_intent="sql",
        predicted_intent="rag",
        routing_correct=False,
        expected_tools=["route_intent"],
        used_tools=["route_intent"],
        tool_path_correct=True,
        should_have_sql=True,
        generated_sql="SELECT 1",
        has_sql=True,
        sql_valid=True,
        answer_format_valid=True,
        confidence="high",
        latency_ms=10.0,
        execution_match=None,
        groundedness_score=1.0,
        groundedness_pass=True,
        unsupported_claims=[],
        groundedness_fail_reasons=[],
        marked_answer="ok",
        error_categories=[],
        failure_bucket=None,
        run_id="r1",
    )
    assert _failure_bucket(item) == "ROUTING_ERROR"


def test_summary_and_gate():
    items = [
        CaseResult(
            case_id="ok1",
            suite="domain",
            language="vi",
            query="q1",
            expected_intent="sql",
            predicted_intent="sql",
            routing_correct=True,
            expected_tools=["route_intent"],
            used_tools=["route_intent"],
            tool_path_correct=True,
            should_have_sql=True,
            generated_sql="SELECT 1",
            has_sql=True,
            sql_valid=True,
            answer_format_valid=True,
            confidence="high",
            latency_ms=100.0,
            execution_match=None,
            groundedness_score=1.0,
            groundedness_pass=True,
            unsupported_claims=[],
            groundedness_fail_reasons=[],
            marked_answer="ok",
            error_categories=[],
            failure_bucket=None,
            run_id="r1",
        ),
        CaseResult(
            case_id="bad1",
            suite="spider",
            language="en",
            query="q2",
            expected_intent="sql",
            predicted_intent="sql",
            routing_correct=True,
            expected_tools=["route_intent", "get_schema"],
            used_tools=["route_intent"],
            tool_path_correct=False,
            should_have_sql=True,
            generated_sql="SELECT * FROM bad_table",
            has_sql=True,
            sql_valid=False,
            answer_format_valid=True,
            confidence="low",
            latency_ms=200.0,
            execution_match=False,
            groundedness_score=0.2,
            groundedness_pass=False,
            unsupported_claims=["numeric_claim:999"],
            groundedness_fail_reasons=["unsupported_claims:numeric_claim:999"],
            marked_answer="bad",
            error_categories=["SQL_VALIDATION_ERROR"],
            failure_bucket="SQL_VALIDATION_ERROR",
            run_id="r2",
        ),
    ]
    summary = summarize(items)
    assert summary["total_cases"] == 2
    passed, failures = _pass_gate(summary)
    assert passed is False
    assert any("tool_path_accuracy" in text for text in failures)
