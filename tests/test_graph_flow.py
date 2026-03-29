from __future__ import annotations

from app.graph import build_sql_v1_graph, new_run_config, to_langgraph_config


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


def _patch_router(monkeypatch, intent: str):
    monkeypatch.setattr(
        "app.graph.nodes.LLMClient.from_env",
        lambda: _DummyRouterClient(intent=intent),
    )


def test_graph_sql_path_runs_end_to_end(monkeypatch):
    _patch_router(monkeypatch, intent="sql")
    graph = build_sql_v1_graph()
    config = to_langgraph_config(new_run_config(thread_id="test-sql", recursion_limit=20))

    out = graph.invoke({"user_query": "DAU 7 ngày gần đây như thế nào?"}, config=config)
    payload = out["final_payload"]

    assert payload["confidence"] in {"high", "medium"}
    assert "SELECT" in payload["generated_sql"].upper()
    assert "route_intent" in payload["used_tools"]
    assert "query_sql" in payload["used_tools"]


def test_graph_rag_route_returns_not_implemented_message(monkeypatch):
    _patch_router(monkeypatch, intent="rag")
    graph = build_sql_v1_graph()
    config = to_langgraph_config(new_run_config(thread_id="test-rag", recursion_limit=20))

    out = graph.invoke({"user_query": "Retention D1 là gì?"}, config=config)
    payload = out["final_payload"]

    assert payload["confidence"] == "low"
    assert "not implemented yet" in payload["answer"]
    assert payload["used_tools"] == ["route_intent"]


def test_graph_fail_fast_on_invalid_sql(monkeypatch):
    _patch_router(monkeypatch, intent="sql")
    monkeypatch.setattr(
        "app.graph.graph.generate_sql",
        lambda state: {"generated_sql": "DELETE FROM daily_metrics", "tool_history": [], "step_count": 1},
    )
    graph = build_sql_v1_graph()
    config = to_langgraph_config(new_run_config(thread_id="test-invalid-sql", recursion_limit=20))

    out = graph.invoke({"user_query": "hãy cập nhật daily_metrics"}, config=config)
    payload = out["final_payload"]
    assert payload["confidence"] == "low"
    assert "validation failed" in payload["answer"]
