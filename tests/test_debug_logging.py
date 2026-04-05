from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.config import load_settings
from app.debug import _filtered_state, trace_node
from app.logger import ensure_debug_file_sink, logger


def test_filtered_state_replaces_large_fields_with_size_hints() -> None:
    state = {
        "user_query": "How many students are male?",
        "schema_context": '{"tables": ["students"]}',
        "tool_history": [{"tool": "get_schema"}],
        "sql_result": {
            "row_count": 2,
            "rows": [{"gender": "male", "count": 10}, {"gender": "female", "count": 12}],
        },
    }

    filtered = _filtered_state(state)

    assert filtered["schema_context"].startswith("<str ")
    assert filtered["tool_history"] == "<list 1 items>"
    assert filtered["sql_result"] == {
        "row_count": 2,
        "columns": ["gender", "count"],
    }


def test_filtered_state_hides_uploaded_file_data() -> None:
    state = {
        "uploaded_file_data": [
            {
                "name": "Performance_of_Stuednts.csv",
                "data": b"gender,math_score\nFemale,66\n",
                "context": "",
            }
        ]
    }

    filtered = _filtered_state(state)

    assert filtered["uploaded_file_data"] == "<list 1 items>"


def test_debug_file_sink_uses_settings_path(monkeypatch, tmp_path: Path) -> None:
    debug_log_path = tmp_path / "custom-debug.log"
    monkeypatch.setenv("DEBUG_LOG_PATH", str(debug_log_path))
    monkeypatch.setenv("DEBUG_LOG_LEVEL", "DEBUG")
    load_settings.cache_clear()

    settings = load_settings()
    ensure_debug_file_sink(settings.debug_log_path, settings.debug_log_level)

    logger.bind(run_id="run-123", node_name="leader_agent", task_id="task-1").debug(
        "debug test line"
    )
    logger.complete()

    assert debug_log_path.exists()
    contents = debug_log_path.read_text(encoding="utf-8")
    assert "run-123" in contents
    assert "leader_agent" in contents
    assert "task-1" in contents
    assert "debug test line" in contents


def test_trace_node_uses_tracer_run_id_when_state_missing(monkeypatch, tmp_path: Path) -> None:
    debug_log_path = tmp_path / "trace-node-debug.log"
    ensure_debug_file_sink(str(debug_log_path), "DEBUG")
    monkeypatch.setattr("app.debug.get_current_tracer", lambda: SimpleNamespace(run_id="trace-run-123"))

    @trace_node("sample_node")
    def _sample_node(state: dict) -> dict:
        return {"ok": True}

    _sample_node({"user_query": "hello"})
    logger.complete()

    contents = debug_log_path.read_text(encoding="utf-8")
    assert "trace-run-123" in contents
    assert "sample_node" in contents
