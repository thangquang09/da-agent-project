from __future__ import annotations

from app.graph import build_sql_v1_graph, new_run_config, to_langgraph_config
from app.graph.nodes import retrieve_context_node, route_intent, synthesize_answer


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


class _FailingRouterClient:
    def chat_completion(self, **kwargs):  # noqa: ANN003
        raise RuntimeError("router unavailable")


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


def test_graph_rag_path_uses_retrieval(monkeypatch):
    _patch_router(monkeypatch, intent="rag")
    graph = build_sql_v1_graph()
    config = to_langgraph_config(new_run_config(thread_id="test-rag", recursion_limit=20))

    out = graph.invoke({"user_query": "Retention D1 là gì?"}, config=config)
    payload = out["final_payload"]

    assert payload["confidence"] in {"low", "medium"}
    assert "retrieve_metric_definition" in payload["used_tools"]
    assert "not implemented yet" not in payload["answer"]


def test_graph_mixed_sql_failure_returns_partial_answer(monkeypatch):
    _patch_router(monkeypatch, intent="mixed")
    monkeypatch.setattr(
        "app.graph.graph.generate_sql",
        lambda state: {"generated_sql": "DELETE FROM daily_metrics", "tool_history": [], "step_count": 1},
    )
    graph = build_sql_v1_graph()
    config = to_langgraph_config(new_run_config(thread_id="test-mixed-fallback", recursion_limit=20))

    out = graph.invoke({"user_query": "Revenue giảm và metric này tính thế nào?"}, config=config)
    payload = out["final_payload"]

    assert payload["confidence"] in {"low", "medium"}
    assert "Partial answer" in payload["answer"]
    assert "retrieve_business_context" in payload["used_tools"]


def test_route_intent_fallback_supports_vietnamese_diacritics(monkeypatch):
    monkeypatch.setattr("app.graph.nodes.LLMClient.from_env", lambda: _FailingRouterClient())

    out = route_intent({"user_query": "DAU 7 ngày gần đây có giảm không?"})

    assert out["intent"] == "sql"
    assert out["intent_reason"].startswith("fallback_due_to_error")


def test_retrieve_context_rag_non_definition_uses_business_context(monkeypatch):
    def _metric_retriever(**kwargs):  # noqa: ANN003
        return {"results": [{"source": "metric", "text": "metric def", "score": 0.9}], "result_count": 1}

    def _business_retriever(**kwargs):  # noqa: ANN003
        return {"results": [{"source": "biz", "text": "caveat", "score": 0.8}], "result_count": 1}

    monkeypatch.setattr("app.graph.nodes.retrieve_metric_definition", _metric_retriever)
    monkeypatch.setattr("app.graph.nodes.retrieve_business_context", _business_retriever)

    out = retrieve_context_node({"user_query": "Revenue có caveat gì?", "intent": "rag"})

    assert out["tool_history"][0]["tool"] == "retrieve_business_context"


def test_mixed_synthesis_treats_empty_sql_result_as_success():
    out = synthesize_answer(
        {
            "intent": "mixed",
            "sql_result": {"rows": [], "row_count": 0},
            "analysis_result": {"summary": "No rows returned.", "trend": "unknown"},
            "retrieved_context": [{"source": "docs", "score": 0.9, "text": "Revenue caveat text"}],
            "errors": [],
            "tool_history": [],
        }
    )

    assert "SQL branch failed" not in out["final_answer"]
    assert "Data signal:" in out["final_answer"]

