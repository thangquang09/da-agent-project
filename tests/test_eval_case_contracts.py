from __future__ import annotations

from pathlib import Path

from evals.case_contracts import EvalCase, dump_cases_jsonl, load_cases_jsonl


def test_dump_and_load_cases_jsonl(tmp_path: Path):
    out_path = tmp_path / "cases.jsonl"
    cases = [
        EvalCase(
            id="case_001",
            suite="domain",
            language="vi",
            query="DAU là bao nhiêu?",
            expected_intent="sql",
            expected_tools=["route_intent"],
            should_have_sql=True,
            target_db_path="data/warehouse/domain_eval.db",
        )
    ]
    dump_cases_jsonl(cases, out_path)
    loaded = load_cases_jsonl(out_path)
    assert len(loaded) == 1
    assert loaded[0].id == "case_001"
    assert loaded[0].suite == "domain"
