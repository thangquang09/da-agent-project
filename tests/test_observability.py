from __future__ import annotations

import json
from pathlib import Path

from app.config import load_settings
from app.main import run_query


class _DummyRouterClient:
    def __init__(self, intent: str):
        self._intent = intent

    def chat_completion(self, **kwargs):  # noqa: ANN003
        return {
            "choices": [
                {
                    "message": {
                        "content": f'{{"intent":"{self._intent}","reason":"test_router"}}'
                    }
                }
            ]
        }


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_run_query_persists_node_and_run_traces(monkeypatch, tmp_path: Path):
    trace_path = tmp_path / "traces.jsonl"
    monkeypatch.setenv("TRACE_JSONL_PATH", str(trace_path))
    load_settings.cache_clear()
    monkeypatch.setattr("app.graph.nodes.LLMClient.from_env", lambda: _DummyRouterClient(intent="sql"))

    payload = run_query("DAU 7 ngày gần đây như thế nào?", recursion_limit=20)
    assert payload["run_id"]

    records = _read_jsonl(trace_path)
    assert any(item.get("record_type") == "node" for item in records)
    run_records = [item for item in records if item.get("record_type") == "run"]
    assert len(run_records) == 1
    assert run_records[0]["status"] == "success"
    assert run_records[0]["routed_intent"] == "sql"


def test_run_query_captures_failure_taxonomy(monkeypatch, tmp_path: Path):
    trace_path = tmp_path / "traces.jsonl"
    monkeypatch.setenv("TRACE_JSONL_PATH", str(trace_path))
    # Ensure deterministic local retrieval path for this unit test.
    monkeypatch.setenv("ENABLE_MCP_TOOL_CLIENT", "0")
    load_settings.cache_clear()
    monkeypatch.setattr("app.graph.nodes.LLMClient.from_env", lambda: _DummyRouterClient(intent="rag"))

    def _raise_retrieval(**kwargs):  # noqa: ANN003
        raise RuntimeError("retriever offline")

    monkeypatch.setattr("app.graph.nodes.retrieve_business_context", _raise_retrieval)
    monkeypatch.setattr("app.graph.nodes.retrieve_metric_definition", _raise_retrieval)

    payload = run_query("Retention D1 là gì?", recursion_limit=20)
    assert "RAG_RETRIEVAL_ERROR" in payload["error_categories"]

    run_records = [item for item in _read_jsonl(trace_path) if item.get("record_type") == "run"]
    assert len(run_records) == 1
    assert "RAG_RETRIEVAL_ERROR" in run_records[0]["error_categories"]

