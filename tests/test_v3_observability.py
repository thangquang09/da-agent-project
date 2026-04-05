from __future__ import annotations

import json
from pathlib import Path

from app.config import load_settings
from app.main import run_query

MULTI_QUERY = (
    '"Có bao nhiêu học sinh nam và bao nhiêu học sinh nữ trong tập dữ liệu này?"\n\n'
    '"Điểm toán (math score) trung bình của toàn bộ học sinh là bao nhiêu?"\n\n'
    '"Có bao nhiêu học sinh đã hoàn thành khóa luyện thi (test prep course = \'completed\')?"'
)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_v3_trace_contains_parallel_subtask_nodes(fake_v3_llm, analytics_db_path, monkeypatch, tmp_path):
    trace_path = tmp_path / "traces.jsonl"
    monkeypatch.setenv("TRACE_JSONL_PATH", str(trace_path))
    load_settings.cache_clear()

    result = run_query(
        MULTI_QUERY,
        db_path=analytics_db_path,
        version="v3",
        thread_id="trace-v3-parallel",
    )

    records = [item for item in _read_jsonl(trace_path) if item.get("run_id") == result["run_id"]]
    node_names = [item["node_name"] for item in records if item.get("record_type") == "node"]
    run_records = [item for item in records if item.get("record_type") == "run"]

    assert "leader_llm_step_1" in node_names
    assert "leader_tool_ask_sql_analyst_parallel" in node_names
    assert "leader_parallel_dispatch" in node_names
    assert "leader_parallel_aggregate" in node_names
    assert "leader_sql_task_1" in node_names
    assert "leader_sql_task_2" in node_names
    assert "leader_sql_task_3" in node_names
    assert run_records[0]["intent"] == "sql"
    assert run_records[0]["used_tools"] == ["ask_sql_analyst_parallel"]


def test_v3_trace_summaries_do_not_emit_null_noise(fake_v3_llm, analytics_db_path, monkeypatch, tmp_path):
    trace_path = tmp_path / "traces.jsonl"
    monkeypatch.setenv("TRACE_JSONL_PATH", str(trace_path))
    load_settings.cache_clear()

    result = run_query(
        "Điểm toán trung bình của toàn bộ học sinh là bao nhiêu?",
        db_path=analytics_db_path,
        version="v3",
        thread_id="trace-v3-single",
    )

    records = [item for item in _read_jsonl(trace_path) if item.get("run_id") == result["run_id"]]
    leader_nodes = [item for item in records if item.get("node_name") == "leader_agent"]
    assert leader_nodes
    input_summary = leader_nodes[0]["input_summary"]
    output_summary = leader_nodes[0]["output_summary"]
    assert "continuity_context" not in input_summary
    assert "continuity_context" not in output_summary
