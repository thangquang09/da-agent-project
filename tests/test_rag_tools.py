from __future__ import annotations

from app.tools import retrieve_business_context, retrieve_metric_definition


def test_retrieve_metric_definition_returns_ranked_chunks():
    result = retrieve_metric_definition("Retention D1 la gi?", top_k=3)
    assert result["result_count"] >= 1
    assert len(result["results"]) <= 3
    assert "source" in result["results"][0]
    assert "score" in result["results"][0]


def test_retrieve_business_context_includes_docs():
    result = retrieve_business_context("Revenue giam co the do dau?", top_k=4)
    assert result["result_count"] >= 1
    sources = {item["source"] for item in result["results"]}
    assert any(src.endswith(".md") for src in sources)

