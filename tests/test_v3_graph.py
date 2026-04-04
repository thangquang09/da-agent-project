from __future__ import annotations

from app.main import run_query

MULTI_QUERY = (
    '"Có bao nhiêu học sinh nam và bao nhiêu học sinh nữ trong tập dữ liệu này?"\n\n'
    '"Điểm toán (math score) trung bình của toàn bộ học sinh là bao nhiêu?"\n\n'
    '"Có bao nhiêu học sinh đã hoàn thành khóa luyện thi (test prep course = \'completed\')?"'
)


def test_v3_single_query_returns_sql_answer(fake_v3_llm, analytics_db_path):
    result = run_query(
        "Điểm toán trung bình của toàn bộ học sinh là bao nhiêu?",
        db_path=analytics_db_path,
        version="v3",
        thread_id="v3-single-query",
    )

    assert result["intent"] == "sql"
    assert "66.08" in result["answer"]
    assert result["used_tools"] == ["ask_sql_analyst"]


def test_v3_multi_query_uses_parallel_tool(fake_v3_llm, analytics_db_path):
    result = run_query(
        MULTI_QUERY,
        db_path=analytics_db_path,
        version="v3",
        thread_id="v3-multi-query",
    )

    assert result["intent"] == "sql"
    assert result["used_tools"] == ["ask_sql_analyst_parallel"]
    assert "518 học sinh nữ" in result["answer"]
    assert "482 học sinh nam" in result["answer"]
    assert "66.08" in result["answer"]
    assert "358" in result["answer"]


def test_v3_rag_stub_path_is_supported(fake_v3_llm, analytics_db_path):
    result = run_query(
        "Retention D1 là gì?",
        db_path=analytics_db_path,
        version="v3",
        thread_id="v3-rag-stub",
    )

    assert result["intent"] == "rag"
    assert result["answer"] == "Không có thông tin"
