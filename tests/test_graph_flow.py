from __future__ import annotations

import pytest

from app.config import load_settings
from app.graph import build_sql_v1_graph, new_run_config, to_langgraph_config
from app.graph.nodes import (
    _build_semantic_context,
    _fallback_context_type,
    detect_context_type,
    generate_sql,
    retrieve_context_node,
    route_intent,
    synthesize_answer,
)


class _DummyRouterClient:
    """Mock LLM client that returns context detection on first call, routing on second."""

    def __init__(self, intent: str):
        self._intent = intent
        self._call_count = 0

    def _get_context_type_from_messages(self, messages: list) -> str:
        """Determine context_type based on input messages."""
        for msg in messages:
            content = msg.get("content", "")
            if "User provided context:" in content and "Uploaded files:" in content:
                return "mixed"
            if "User provided context:" in content:
                return "user_provided"
            if "Uploaded files:" in content and "data.csv" in content:
                return "csv_auto"
        return "default"

    def chat_completion(self, **kwargs):  # noqa: ANN003
        self._call_count += 1
        messages = kwargs.get("messages", [])

        if self._call_count == 1:
            context_type = self._get_context_type_from_messages(messages)
            return {
                "choices": [
                    {
                        "message": {
                            "content": f'{{"context_type":"{context_type}","needs_semantic_context":{str(context_type != "default").lower()}}}'
                        }
                    }
                ]
            }

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
    client = _DummyRouterClient(intent=intent)
    monkeypatch.setattr(
        "app.graph.nodes.LLMClient.from_env",
        lambda: client,
    )


@pytest.fixture(autouse=True)
def disable_llm(monkeypatch):
    monkeypatch.setenv("ENABLE_LLM_SQL_GENERATION", "0")
    load_settings.cache_clear()


def test_graph_sql_path_runs_end_to_end(monkeypatch):
    class _DummySqlRouterClient:
        def __init__(self):
            self.call_count = 0

        def chat_completion(self, **kwargs):  # noqa: ANN003
            self.call_count += 1
            if self.call_count == 1:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": '{"context_type":"default","needs_semantic_context":false}'
                            }
                        }
                    ]
                }
            elif self.call_count == 2:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": '{"intent":"sql","reason":"llm_router"}'
                            }
                        }
                    ]
                }
            else:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": "```sql\nSELECT date, dau FROM daily_metrics ORDER BY date DESC LIMIT 7\n```"
                            }
                        }
                    ]
                }

    client = _DummySqlRouterClient()
    monkeypatch.setattr("app.graph.nodes.LLMClient.from_env", lambda: client)
    monkeypatch.setenv("ENABLE_LLM_SQL_GENERATION", "1")
    load_settings.cache_clear()

    graph = build_sql_v1_graph()
    config = to_langgraph_config(
        new_run_config(thread_id="test-sql", recursion_limit=20)
    )

    out = graph.invoke({"user_query": "DAU 7 ngày gần đây như thế nào?"}, config=config)
    payload = out["final_payload"]

    assert payload["confidence"] in {"high", "medium"}
    assert "SELECT" in payload["generated_sql"].upper()
    assert "route_intent" in payload["used_tools"]
    assert "query_sql" in payload["used_tools"]


def test_graph_rag_path_uses_retrieval(monkeypatch):
    class _DummyRagRouterClient:
        def __init__(self):
            self.call_count = 0

        def chat_completion(self, **kwargs):  # noqa: ANN003
            self.call_count += 1
            if self.call_count == 1:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": '{"context_type":"default","needs_semantic_context":false}'
                            }
                        }
                    ]
                }
            elif self.call_count == 2:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": '{"intent":"rag","reason":"llm_router"}'
                            }
                        }
                    ]
                }
            elif self.call_count == 3:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": '{"retrieval_type":"metric_definition","reason":"user asks for definition"}'
                            }
                        }
                    ]
                }
            else:
                return {
                    "choices": [
                        {"message": {"content": "Metric definition retrieved."}}
                    ]
                }

    client = _DummyRagRouterClient()
    monkeypatch.setattr("app.graph.nodes.LLMClient.from_env", lambda: client)

    graph = build_sql_v1_graph()
    config = to_langgraph_config(
        new_run_config(thread_id="test-rag", recursion_limit=20)
    )

    out = graph.invoke({"user_query": "Retention D1 là gì?"}, config=config)
    payload = out["final_payload"]

    assert payload["confidence"] in {"low", "medium"}
    assert any("retrieve" in tool for tool in payload["used_tools"])
    assert "not implemented yet" not in payload["answer"]


def test_graph_mixed_sql_failure_returns_partial_answer(monkeypatch):
    _patch_router(monkeypatch, intent="mixed")
    # Mock generate_sql to simulate self-correction behavior
    # Must properly increment retry_count to avoid infinite loops
    call_count = [0]

    def mock_generate_sql(state):
        call_count[0] += 1
        # Properly increment retry count when there's a previous error
        current_retry = state.get("sql_retry_count", 0)
        last_error = state.get("sql_last_error")
        new_retry_count = current_retry + 1 if last_error else current_retry
        return {
            "generated_sql": "DELETE FROM daily_metrics",
            "sql_retry_count": new_retry_count,
            "tool_history": [],
            "step_count": 1,
        }

    monkeypatch.setattr(
        "app.graph.graph.generate_sql",
        mock_generate_sql,
    )
    graph = build_sql_v1_graph()
    config = to_langgraph_config(
        new_run_config(thread_id="test-mixed-fallback", recursion_limit=25)
    )

    out = graph.invoke(
        {"user_query": "Revenue giảm và metric này tính thế nào?"}, config=config
    )
    payload = out["final_payload"]

    assert payload["confidence"] in {"low", "medium"}
    # When SQL fails, should show context-only response
    assert (
        any(
            keyword in payload["answer"]
            for keyword in ["tài liệu nghiệp vụ", "business docs", "metric", "Revenue"]
        )
        or "Partial answer" in payload["answer"]
    )
    assert "retrieve_business_context" in payload["used_tools"]


def test_route_intent_llm_routes_vietnamese_diacritics(monkeypatch):
    class _DummyRouterClient:
        def chat_completion(self, **kwargs):  # noqa: ANN003
            return {
                "choices": [
                    {"message": {"content": '{"intent":"sql","reason":"llm_router"}'}}
                ]
            }

    monkeypatch.setattr(
        "app.graph.nodes.LLMClient.from_env", lambda: _DummyRouterClient()
    )

    out = route_intent({"user_query": "DAU 7 ngày gần đây có giảm không?"})

    assert out["intent"] == "sql"
    assert out["intent_reason"] == "llm_router"


def test_retrieve_context_rag_non_definition_uses_business_context(monkeypatch):
    def _metric_retriever(**kwargs):  # noqa: ANN003
        return {
            "results": [{"source": "metric", "text": "metric def", "score": 0.9}],
            "result_count": 1,
        }

    def _business_retriever(**kwargs):  # noqa: ANN003
        return {
            "results": [{"source": "biz", "text": "caveat", "score": 0.8}],
            "result_count": 1,
        }

    monkeypatch.setattr("app.graph.nodes.retrieve_metric_definition", _metric_retriever)
    monkeypatch.setattr(
        "app.graph.nodes.retrieve_business_context", _business_retriever
    )

    out = retrieve_context_node(
        {"user_query": "Revenue có caveat gì?", "intent": "rag"}
    )

    assert out["tool_history"][0]["tool"] == "retrieve_business_context"


def test_mixed_synthesis_treats_empty_sql_result_as_success():
    out = synthesize_answer(
        {
            "intent": "mixed",
            "sql_result": {"rows": [], "row_count": 0},
            "analysis_result": {"summary": "No rows returned.", "trend": "unknown"},
            "retrieved_context": [
                {"source": "docs", "score": 0.9, "text": "Revenue caveat text"}
            ],
            "errors": [],
            "tool_history": [],
        }
    )

    # Should not show failure message, should show context + no data message
    assert "SQL branch failed" not in out["final_answer"]
    # Response should contain context evidence and indicate no SQL data
    assert "Context bổ sung" in out["final_answer"] or "Revenue" in out["final_answer"]


def test_route_intent_llm_handles_natural_question_as_unknown(monkeypatch):
    class _DummyRouterClient:
        def chat_completion(self, **kwargs):  # noqa: ANN003
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"intent":"unknown","reason":"llm_router"}'
                        }
                    }
                ]
            }

    monkeypatch.setattr(
        "app.graph.nodes.LLMClient.from_env", lambda: _DummyRouterClient()
    )

    out = route_intent({"user_query": "bạn có thể làm gì?"})

    assert out["intent"] == "unknown"
    assert out["intent_reason"] == "llm_router"


def test_graph_unknown_intent_goes_direct_to_synthesize(monkeypatch):
    class _DummyUnknownRouterClient:
        def chat_completion(self, **kwargs):  # noqa: ANN003
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"intent":"unknown","reason":"llm_router"}'
                        }
                    }
                ]
            }

    class _DummyFallbackClient:
        def chat_completion(self, **kwargs):  # noqa: ANN003
            return {
                "choices": [
                    {
                        "message": {
                            "content": "I can help with data analysis questions about metrics, trends, and KPIs."
                        }
                    }
                ]
            }

    def _mock_llm():
        class Client:
            def __init__(self):
                self.call_count = 0

            def chat_completion(self, **kwargs):
                self.call_count += 1
                if self.call_count == 1:
                    return {
                        "choices": [
                            {
                                "message": {
                                    "content": '{"intent":"unknown","reason":"llm_router"}'
                                }
                            }
                        ]
                    }
                else:
                    return {
                        "choices": [
                            {
                                "message": {
                                    "content": "I can help with data analysis questions about metrics, trends, and KPIs."
                                }
                            }
                        ]
                    }

        return Client()

    client = _mock_llm()
    monkeypatch.setattr("app.graph.nodes.LLMClient.from_env", lambda: client)

    graph = build_sql_v1_graph()
    config = to_langgraph_config(
        new_run_config(thread_id="test-unknown", recursion_limit=20)
    )

    out = graph.invoke({"user_query": "bạn có thể làm gì?"}, config=config)
    payload = out["final_payload"]

    assert out["intent"] == "unknown"
    assert "detect_context_type" in payload["used_tools"]
    assert "route_intent" in payload["used_tools"]
    assert len(payload["answer"]) > 0


def test_generate_sql_extracts_from_markdown_fence(monkeypatch):
    class _DummySqlClient:
        def chat_completion(self, **kwargs):  # noqa: ANN003
            return {
                "choices": [
                    {
                        "message": {
                            "content": "```sql\nSELECT date, dau FROM daily_metrics ORDER BY date DESC LIMIT 7\n```"
                        }
                    }
                ]
            }

    monkeypatch.setenv("ENABLE_LLM_SQL_GENERATION", "1")
    load_settings.cache_clear()
    monkeypatch.setattr("app.graph.nodes.LLMClient.from_env", lambda: _DummySqlClient())

    out = generate_sql(
        {"user_query": "DAU 7 ngày gần đây như thế nào?", "schema_context": "{}"}
    )
    assert out["generated_sql"].upper().startswith("SELECT")


class TestDetectContextType:
    def test_fallback_context_type_with_user_semantic_context(self):
        context_type, needs_ctx, semantic = _fallback_context_type(
            user_semantic_context="This is a UK online retail dataset",
            uploaded_files=[],
        )
        assert context_type == "user_provided"
        assert needs_ctx is True
        assert semantic == "This is a UK online retail dataset"

    def test_fallback_context_type_with_uploaded_files_only(self):
        context_type, needs_ctx, semantic = _fallback_context_type(
            user_semantic_context="",
            uploaded_files=["/path/to/file.csv"],
        )
        assert context_type == "csv_auto"
        assert needs_ctx is True
        assert semantic is None

    def test_fallback_context_type_with_both(self):
        context_type, needs_ctx, semantic = _fallback_context_type(
            user_semantic_context="Retail data context",
            uploaded_files=["/path/to/file.csv"],
        )
        assert context_type == "mixed"
        assert needs_ctx is True
        assert semantic == "Retail data context"

    def test_fallback_context_type_with_neither(self):
        context_type, needs_ctx, semantic = _fallback_context_type(
            user_semantic_context="",
            uploaded_files=[],
        )
        assert context_type == "default"
        assert needs_ctx is False
        assert semantic is None

    def test_detect_context_type_node(self, monkeypatch):
        class _DummyContextClient:
            def chat_completion(self, **kwargs):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": '{"context_type":"user_provided","needs_semantic_context":true}'
                            }
                        }
                    ]
                }

        monkeypatch.setattr(
            "app.graph.nodes.LLMClient.from_env",
            lambda: _DummyContextClient(),
        )
        state = {
            "user_query": "Test query",
            "user_semantic_context": "Dataset about customer transactions",
            "uploaded_files": [],
            "step_count": 0,
        }
        out = detect_context_type(state)
        assert out["context_type"] == "user_provided"
        assert out["needs_semantic_context"] is True
        assert out["tool_history"][0]["tool"] == "detect_context_type"

    def test_detect_context_type_node_with_files(self, monkeypatch):
        class _DummyContextClient:
            def chat_completion(self, **kwargs):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": '{"context_type":"csv_auto","needs_semantic_context":true}'
                            }
                        }
                    ]
                }

        monkeypatch.setattr(
            "app.graph.nodes.LLMClient.from_env",
            lambda: _DummyContextClient(),
        )
        state = {
            "user_query": "Test query",
            "user_semantic_context": "",
            "uploaded_files": ["data.csv"],
            "step_count": 0,
        }
        out = detect_context_type(state)
        assert out["context_type"] == "csv_auto"


class TestBuildSemanticContext:
    def test_build_semantic_context_with_user_context(self):
        state = {
            "user_semantic_context": "This is a retail dataset",
            "retrieved_dataset_context": [],
        }
        result = _build_semantic_context(state)
        assert "User provided" in result
        assert "This is a retail dataset" in result

    def test_build_semantic_context_with_retrieved_chunks(self):
        state = {
            "user_semantic_context": "",
            "retrieved_dataset_context": [
                {
                    "source": "uci_retail.md",
                    "text": "InvoiceNo indicates transaction ID",
                    "score": 0.9,
                }
            ],
        }
        result = _build_semantic_context(state)
        assert "Relevant context" in result
        assert "InvoiceNo indicates transaction ID" in result

    def test_build_semantic_context_empty(self):
        state = {
            "user_semantic_context": "",
            "retrieved_dataset_context": [],
        }
        result = _build_semantic_context(state)
        assert result == ""


class TestGraphWithContextTypes:
    def test_graph_with_user_semantic_context(self, monkeypatch):
        _patch_router(monkeypatch, intent="sql")
        graph = build_sql_v1_graph()
        config = to_langgraph_config(
            new_run_config(thread_id="test-context", recursion_limit=25)
        )

        out = graph.invoke(
            {
                "user_query": "What is the revenue trend?",
                "user_semantic_context": "This dataset contains UK online retail transactions from 2009-2011",
            },
            config=config,
        )
        payload = out["final_payload"]
        assert payload["context_type"] == "user_provided"
        assert "detect_context_type" in payload["used_tools"]

    def test_graph_with_csv_auto_context(self, monkeypatch):
        _patch_router(monkeypatch, intent="sql")
        graph = build_sql_v1_graph()
        config = to_langgraph_config(
            new_run_config(thread_id="test-csv-auto", recursion_limit=25)
        )

        out = graph.invoke(
            {
                "user_query": "Show me top customers",
                "uploaded_files": ["/tmp/data.csv"],
            },
            config=config,
        )
        payload = out["final_payload"]
        assert payload["context_type"] == "csv_auto"

    def test_graph_with_mixed_context(self, monkeypatch):
        _patch_router(monkeypatch, intent="sql")
        graph = build_sql_v1_graph()
        config = to_langgraph_config(
            new_run_config(thread_id="test-mixed", recursion_limit=25)
        )

        out = graph.invoke(
            {
                "user_query": "Revenue by country",
                "user_semantic_context": "CustomerID represents unique customer",
                "uploaded_files": ["/tmp/data.csv"],
            },
            config=config,
        )
        payload = out["final_payload"]
        assert payload["context_type"] == "mixed"

    def test_graph_default_context(self, monkeypatch):
        class _DummySqlClient:
            def __init__(self):
                self.call_count = 0

            def chat_completion(self, **kwargs):  # noqa: ANN003
                self.call_count += 1
                if self.call_count == 1:
                    return {
                        "choices": [
                            {
                                "message": {
                                    "content": '{"context_type":"default","needs_semantic_context":false}'
                                }
                            }
                        ]
                    }
                elif self.call_count == 2:
                    return {
                        "choices": [
                            {
                                "message": {
                                    "content": '{"intent":"sql","reason":"llm_router"}'
                                }
                            }
                        ]
                    }
                else:
                    return {
                        "choices": [
                            {
                                "message": {
                                    "content": "```sql\nSELECT date, dau FROM daily_metrics ORDER BY date DESC LIMIT 7\n```"
                                }
                            }
                        ]
                    }

        client = _DummySqlClient()
        monkeypatch.setattr("app.graph.nodes.LLMClient.from_env", lambda: client)
        monkeypatch.setenv("ENABLE_LLM_SQL_GENERATION", "1")
        load_settings.cache_clear()

        graph = build_sql_v1_graph()
        config = to_langgraph_config(
            new_run_config(thread_id="test-default", recursion_limit=25)
        )

        out = graph.invoke(
            {"user_query": "DAU 7 ngày gần đây"},
            config=config,
        )
        payload = out["final_payload"]
        assert payload["context_type"] == "default"
        assert "SELECT" in payload["generated_sql"].upper()


class TestSynthesizeAnswerWithContextType:
    def test_synthesize_answer_includes_context_type(self):
        out = synthesize_answer(
            {
                "intent": "sql",
                "sql_result": {
                    "rows": [{"date": "2024-01-01", "dau": 100}],
                    "row_count": 1,
                },
                "analysis_result": {"summary": "DAU is 100", "trend": "stable"},
                "retrieved_context": [],
                "retrieved_dataset_context": [],
                "errors": [],
                "tool_history": [],
                "context_type": "user_provided",
                "user_semantic_context": "Test context",
                "schema_context": "{}",
                "dataset_context": "{}",
            }
        )
        assert out["final_payload"]["context_type"] == "user_provided"
