"""Integration tests using real LLM.

These tests use the real LLM API to catch actual errors that FakeLLM might miss.
Enable by running:
    pytest tests/test_real_llm.py --real-llm
    USE_REAL_LLM=1 pytest tests/test_real_llm.py

Note: These tests require LLM_API_KEY to be set and will consume API quota.
"""
from __future__ import annotations

import pytest

from tests.conftest import REAL_LLM_ENABLED


class TestRealLLMIntegration:
    """Integration tests using real LLM to catch actual errors."""

    @pytest.mark.real_llm
    def test_single_query_with_real_llm(self, real_v3_llm, analytics_db_path):
        """Test single query execution with real LLM."""
        from app.graph.graph import build_sql_v3_graph

        graph = build_sql_v3_graph()
        graph.update_state(
            thread_id="test-real-llm-single",
            user_query="Số lượng học sinh nam là bao nhiêu?",
            xml_database_context="",
            session_id="test-real-llm-session",
        )

        result = graph.invoke({}, config={"recursion_limit": 50})

        # Verify real LLM response
        assert result["answer"]
        assert "SQL" in result or "answer" in result
        assert result["confidence"] > 0

    @pytest.mark.real_llm
    def test_task_grounder_with_real_llm(self, real_v3_llm):
        """Test task grounder with real LLM to detect routing issues."""
        from app.graph.task_grounder import TaskGrounder

        grounder = TaskGrounder(llm_client=real_v3_llm)

        # Test different query types
        queries = [
            "Tổng số doanh thu là bao nhiêu?",
            "Vẽ biểu đồ xu hướng doanh thu theo tháng",
            "Top 5 sản phẩm bán chạy nhất",
        ]

        for query in queries:
            profile = grounder.ground_query(query=query, session_context="")
            # Verify real LLM returns valid structured output
            assert profile.mode in ["sql", "mixed", "report", "chitchat"]
            assert profile.confidence >= 0
            assert profile.capabilities

    @pytest.mark.real_llm
    def test_sql_generation_with_real_llm(self, real_v3_llm, analytics_db_path):
        """Test SQL generation with real LLM to catch SQL errors."""
        from app.graph.nodes import ask_sql_analyst

        result = ask_sql_analyst(
            query="Số lượng học sinh nam trong tập dữ liệu?",
            xml_database_context="",
            llm_client=real_v3_llm,
            session_id="test-real-llm-sql",
        )

        # Verify SQL is generated and valid
        assert "sql" in result
        assert result["sql"]
        assert "SELECT" in result["sql"].upper()
        assert "học sinh" in result["sql"].lower() or "student" in result["sql"].lower()

    @pytest.mark.real_llm
    def test_error_handling_with_real_llm(self, real_v3_llm):
        """Test error handling with real LLM to catch unexpected failures."""
        from app.graph.nodes import ask_sql_analyst

        # Test with malformed query
        result = ask_sql_analyst(
            query="This is not a valid data question at all!!!",
            xml_database_context="",
            llm_client=real_v3_llm,
            session_id="test-real-llm-error",
        )

        # Real LLM should handle this gracefully
        assert "confidence" in result
        assert result["confidence"] >= 0
        # Should fall back to chitchat or error handling
