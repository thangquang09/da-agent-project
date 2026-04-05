from __future__ import annotations

from tests.conftest import FakeV3LLMClient, REPORT_QUERY

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


def test_v3_simple_male_query_stays_on_fast_path(fake_v3_llm, analytics_db_path):
    result = run_query(
        "data này có bao nhiêu người giới tính nam",
        db_path=analytics_db_path,
        version="v3",
        thread_id="v3-simple-male-query",
    )

    assert result["intent"] == "sql"
    assert result["used_tools"] == ["ask_sql_analyst"]
    assert result.get("response_mode") == "answer"
    assert result.get("report_markdown") is None
    assert "482" in result["answer"]


def test_v3_explicit_report_query_routes_to_report_path(fake_v3_llm, analytics_db_path):
    result = run_query(
        REPORT_QUERY,
        db_path=analytics_db_path,
        version="v3",
        thread_id="v3-report-query",
    )

    assert result["intent"] == "sql"
    assert result.get("response_mode") == "report"
    assert result["used_tools"] == ["generate_report"]
    assert result.get("report_markdown")
    assert "# Báo cáo phân tích dữ liệu học sinh" in result["report_markdown"]


# ---------------------------------------------------------------------------
# Helper fake clients for unhappy-path / error-recovery tests
# ---------------------------------------------------------------------------


class FailOnceSQLClient(FakeV3LLMClient):
    """Returns bad SQL on the first _sql_response call, then correct SQL on retries.

    The call counter is per-instance so parallel tests don't interfere.

    Note: In the V3 graph the sql_worker_graph executes the worker as a single-shot
    pipeline (generate → validate → execute) with no built-in retry loop.
    A second call would only happen if the leader chose to call ask_sql_analyst again,
    which it does not.  The test therefore verifies graceful degradation on the
    first bad-SQL call rather than a two-call self-correction scenario.
    """

    def __init__(self) -> None:
        super().__init__()
        self._sql_call_count: int = 0

    def _sql_response(self, user: str) -> dict:
        self._sql_call_count += 1
        if self._sql_call_count == 1:
            # First attempt: reference a table that does not exist → execution error
            return {"choices": [{"message": {"content": "SELECT * FROM NonExistentTable"}}]}
        # Subsequent attempts (if any): delegate to the correct parent implementation
        return super()._sql_response(user)


class AlwaysFailSQLClient(FakeV3LLMClient):
    """Always returns SQL that references a non-existent table.

    Used to simulate exhausted retries / persistent failures.
    """

    def _sql_response(self, user: str) -> dict:
        return {"choices": [{"message": {"content": "SELECT * FROM NonExistentTable"}}]}


class DMLThenCorrectSQLClient(FakeV3LLMClient):
    """Returns a DML statement (blocked by validation) on the first call,
    then correct SQL on subsequent calls.

    Like FailOnceSQLClient, no automatic retry loop exists inside the V3 worker,
    so only the first bad call is exercised before graceful degradation.
    """

    def __init__(self) -> None:
        super().__init__()
        self._sql_call_count: int = 0

    def _sql_response(self, user: str) -> dict:
        self._sql_call_count += 1
        if self._sql_call_count == 1:
            # First attempt: DML that validate_sql must block
            return {
                "choices": [
                    {"message": {"content": "DROP TABLE Performance_of_Stuednts"}}
                ]
            }
        # Subsequent attempts: delegate to the correct parent implementation
        return super()._sql_response(user)


# ---------------------------------------------------------------------------
# Unhappy-path / error-recovery tests
# ---------------------------------------------------------------------------


def test_v3_sql_self_correction_on_invalid_sql(monkeypatch, analytics_db_path):
    """SQL LLM returns a bad table name → worker execution fails → graceful degraded answer.

    In the V3 architecture the sql_worker_graph subgraph has no built-in retry loop.
    The leader receives the failed task result and falls back to a graceful degraded
    answer without raising an unhandled exception.
    """
    client = FailOnceSQLClient()
    monkeypatch.setattr("app.graph.nodes.LLMClient.from_env", lambda: client)
    monkeypatch.setattr("app.graph.sql_worker_graph.LLMClient.from_env", lambda: client)

    result = run_query(
        "Điểm toán trung bình của toàn bộ học sinh là bao nhiêu?",
        db_path=analytics_db_path,
        version="v3",
        thread_id="v3-retry-test-1",
    )

    # The bad SQL was generated — confirm the client was called at all
    assert client._sql_call_count >= 1

    # The pipeline must return a dict with a non-empty answer (no unhandled exception)
    assert isinstance(result, dict)
    assert result.get("answer") is not None
    assert isinstance(result["answer"], str)
    assert result["answer"] != ""

    # Intent should still be recognised as sql (the leader decided sql intent)
    assert result.get("intent") == "sql"

    # The failure should be captured — either in errors or error_categories
    has_error_signal = (
        bool(result.get("errors"))
        or bool(result.get("error_categories"))
    )
    assert has_error_signal, (
        f"Expected errors/error_categories to be populated after bad SQL, got: "
        f"errors={result.get('errors')}, error_categories={result.get('error_categories')}"
    )


def test_v3_sql_self_correction_on_dml_injection(monkeypatch, analytics_db_path):
    """SQL LLM returns a DML statement blocked by the validator → graceful degraded answer.

    The validate_sql tool rejects any non-SELECT/CTE statement.  The worker then
    marks its task as failed.  The leader synthesises a degraded answer instead of
    crashing.
    """
    client = DMLThenCorrectSQLClient()
    monkeypatch.setattr("app.graph.nodes.LLMClient.from_env", lambda: client)
    monkeypatch.setattr("app.graph.sql_worker_graph.LLMClient.from_env", lambda: client)

    result = run_query(
        "Điểm toán trung bình của toàn bộ học sinh là bao nhiêu?",
        db_path=analytics_db_path,
        version="v3",
        thread_id="v3-retry-test-2",
    )

    # The DML attempt must have been made
    assert client._sql_call_count >= 1

    # No unhandled exception — result is always a dict
    assert isinstance(result, dict)
    assert result.get("answer") is not None
    assert isinstance(result["answer"], str)
    assert result["answer"] != ""

    # Intent remains sql (leader chose sql path)
    assert result.get("intent") == "sql"

    # The DML rejection is reflected as an error signal
    has_error_signal = (
        bool(result.get("errors"))
        or bool(result.get("error_categories"))
    )
    assert has_error_signal, (
        f"Expected errors/error_categories after DML rejection, got: "
        f"errors={result.get('errors')}, error_categories={result.get('error_categories')}"
    )


def test_v3_sql_exhausted_retries_returns_graceful_error(monkeypatch, analytics_db_path):
    """SQL LLM always returns invalid SQL — simulates a stubborn persistent failure.

    After max attempts the pipeline should return a graceful degraded answer and
    never raise an unhandled exception.
    """
    client = AlwaysFailSQLClient()
    monkeypatch.setattr("app.graph.nodes.LLMClient.from_env", lambda: client)
    monkeypatch.setattr("app.graph.sql_worker_graph.LLMClient.from_env", lambda: client)

    # Must NOT raise — the graph handles the failure gracefully
    result = run_query(
        "Điểm toán trung bình của toàn bộ học sinh là bao nhiêu?",
        db_path=analytics_db_path,
        version="v3",
        thread_id="v3-retry-test-3",
    )

    assert isinstance(result, dict), "run_query should always return a dict"

    # Pipeline must produce some answer string (even if it is an error message)
    assert result.get("answer") is not None
    assert isinstance(result["answer"], str)
    assert result["answer"] != ""

    # The errors list or error_categories must be non-empty to signal the failure
    has_error_signal = (
        bool(result.get("errors"))
        or bool(result.get("error_categories"))
    )
    assert has_error_signal, (
        "Expected errors or error_categories to be populated after exhausted retries, "
        f"got: errors={result.get('errors')}, error_categories={result.get('error_categories')}"
    )
