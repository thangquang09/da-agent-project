from __future__ import annotations

from tests.conftest import FakeV3LLMClient, REPORT_QUERY, REPORT_WITH_VIZ_QUERY

from app.main import run_query
from app.graph.report_subgraph import (
    _build_report_insight_messages,
    _deterministic_critic_issues,
    _section_writer_payload,
    _validate_section_semantics,
    profiler_sampler_node,
    report_finalize_node,
)

MULTI_QUERY = (
    '"Có bao nhiêu học sinh nam và bao nhiêu học sinh nữ trong tập dữ liệu này?"\n\n'
    '"Điểm toán (math score) trung bình của toàn bộ học sinh là bao nhiêu?"\n\n'
    "\"Có bao nhiêu học sinh đã hoàn thành khóa luyện thi (test prep course = 'completed')?\""
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


def test_v3_explicit_report_query_routes_to_report_path(
    fake_v3_llm, fake_report_analysis, analytics_db_path
):
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


def test_v3_simple_sql_fast_path_does_not_call_report_analysis(
    fake_v3_llm, monkeypatch, analytics_db_path
):
    def _unexpected(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError(
            "report-only sandbox analysis should not run for simple SQL queries"
        )

    service = type(
        "UnexpectedVisualizationService",
        (),
        {"generate_grounded_report_analysis": staticmethod(_unexpected)},
    )()
    monkeypatch.setattr(
        "app.graph.report_subgraph.get_visualization_service", lambda: service
    )

    result = run_query(
        "Điểm toán trung bình của toàn bộ học sinh là bao nhiêu?",
        db_path=analytics_db_path,
        version="v3",
        thread_id="v3-simple-fast-path-no-report-analysis",
    )

    assert result["intent"] == "sql"
    assert result["used_tools"] == ["ask_sql_analyst"]


def test_v3_report_with_visualization_language_still_routes_to_report_path(
    fake_v3_llm, fake_report_analysis, analytics_db_path
):
    result = run_query(
        REPORT_WITH_VIZ_QUERY,
        db_path=analytics_db_path,
        version="v3",
        thread_id="v3-report-viz-query",
    )

    assert result["intent"] == "sql"
    assert result.get("response_mode") == "report"
    assert result["used_tools"] == ["generate_report"]
    assert result.get("report_markdown")


def test_report_insight_prompt_uses_grouped_rows_without_cross_row_metrics():
    section = {
        "title": "Family Structure Impact on Survival",
        "analysis_query": "Analyze family size and survival",
        "computed_stats": {
            "row_count": 9,
            "metrics": {
                "max_value": {
                    "value": 0.724138,
                    "display_value": "0.724138",
                    "label": "survival_rate",
                },
                "total_value": {
                    "value": 891,
                    "display_value": "891",
                    "label": "total_passengers",
                },
            },
            "grouped_rows": [
                {
                    "family_size": 0,
                    "total_passengers": 537,
                    "survived_count": 163,
                    "survival_rate": 0.303538,
                },
                {
                    "family_size": 3,
                    "total_passengers": 29,
                    "survived_count": 21,
                    "survival_rate": 0.724138,
                },
            ],
            "row_bindings": {
                "group_columns": ["family_size"],
                "metric_columns": [
                    "total_passengers",
                    "survived_count",
                    "survival_rate",
                ],
            },
            "data_quality": {"warnings": []},
        },
    }

    messages = _build_report_insight_messages(
        {"report_request": "Analyze the Titanic dataset", "report_data_profile": {}},
        section,
    )

    message_text = messages[-1]["content"]
    assert '"grouped_rows"' in message_text
    assert '"row_bindings"' in message_text
    assert '"max_value"' not in message_text


def test_report_finalize_uses_safe_fallback_when_critic_still_rejects():
    state = {
        "critic_verdict": "REVISE",
        "report_plan": {"title": "Titanic Report"},
        "report_draft": "# bad draft\n\nUnsupported synthesis",
        "report_sections": [
            {
                "section_id": "1",
                "title": "Family Structure and Survival Patterns",
                "status": "done",
                "insight_markdown": "Hành khách đi một mình có tỷ lệ sống sót 30,35%.",
                "limitations": ["Thiếu biến vị trí cabin trong phân tích này."],
                "sql_result": {"row_count": 2},
            }
        ],
        "step_count": 5,
    }

    update = report_finalize_node(state)

    assert "Unsupported synthesis" not in update["final_payload"]["report_markdown"]
    assert "quy trình sơ tán" not in update["final_payload"]["report_markdown"]
    assert (
        "Hành khách đi một mình có tỷ lệ sống sót 30,35%."
        in update["final_payload"]["report_markdown"]
    )
    assert update["final_payload"]["confidence"] == "low"
    assert "did not pass the critic" in update["final_payload"]["confidence_rationale"]
    assert update["tool_history"][0]["used_safe_fallback"] is True


def test_section_writer_payload_includes_citations_and_compact_stats():
    payload = _section_writer_payload(
        {
            "section_id": "sec-1",
            "title": "Overview",
            "analysis_query": "Summarize the main findings",
            "status": "done",
            "analysis_status": "done",
            "insight_markdown": "Revenue was concentrated in two segments.",
            "insight_citations": [
                {"json_path": "metrics.total_value", "value": "1000"}
            ],
            "computed_stats": {
                "row_count": 12,
                "metrics": {"total_value": {"value": 1000, "display_value": "1000"}},
                "comparisons": {"delta": {"value": 120, "display_value": "120"}},
                "rankings": {"top_items": [{"label": "A", "value": 700}]},
                "data_quality": {"warnings": ["Small sample"]},
                "grouped_rows": [
                    {"segment": "A", "revenue": 700},
                    {"segment": "B", "revenue": 300},
                ],
                "row_bindings": {
                    "group_columns": ["segment"],
                    "metric_columns": ["revenue"],
                },
            },
            "limitations": ["Small sample"],
        }
    )

    assert payload["analysis_status"] == "done"
    assert payload["citations"] == [
        {"json_path": "metrics.total_value", "value": "1000"}
    ]
    assert payload["computed_stats"]["row_count"] == 12
    assert payload["computed_stats"]["grouped_rows"] == [
        {"segment": "A", "revenue": 700},
        {"segment": "B", "revenue": 300},
    ]


def test_profiler_sampler_ignores_uploaded_tables_not_in_schema(monkeypatch):
    executed_sql: list[str] = []

    def _fake_query_sql(sql: str, db_path=None):  # noqa: ANN001, ARG001
        executed_sql.append(sql)
        if "ORDER BY RANDOM()" in sql:
            return {"rows": [{"id": 1, "value": 10}], "columns": ["id", "value"]}
        return {"rows": [{"total_rows": 1, "distinct_count": 1, "null_count": 0}]}

    monkeypatch.setattr("app.graph.report_subgraph.query_sql", _fake_query_sql)

    update = profiler_sampler_node(
        {
            "xml_database_context": '<database><table name="valid_table"></table></database>',
            "table_contexts": {
                "missing_table": "not in schema",
                "valid_table": "in schema",
            },
        }
    )

    assert list(update["report_sample_data"].keys()) == ["valid_table"]
    assert all('"valid_table"' in sql for sql in executed_sql)


def test_semantic_validator_flags_average_of_rates_risk():
    section = _validate_section_semantics(
        {
            "title": "Tỷ lệ chuyển đổi theo nhóm",
            "analysis_query": "Tỷ lệ chuyển đổi trung bình theo từng nhóm khách hàng là bao nhiêu?",
            "analysis_type": "comparative",
            "validated_sql": 'SELECT AVG("conversion_rate") AS avg_conversion_rate FROM "campaign_metrics"',
            "computed_stats": {
                "row_count": 3,
                "grouped_rows": [{"segment": "A", "conversion_rate": 0.2}],
                "data_quality": {"warnings": []},
            },
            "chart_manifest": {"chart_type": "table"},
            "sql_result": {"row_count": 3},
        }
    )

    assert section["analysis_type"] == "comparative"
    assert section["semantic_status"] == "warning"
    assert section["section_confidence"] == "low"
    assert any(
        "average-of-averages" in warning for warning in section["semantic_warnings"]
    )


def test_semantic_validator_marks_missing_trend_series():
    section = _validate_section_semantics(
        {
            "title": "Xu hướng doanh thu",
            "analysis_query": "Doanh thu thay đổi theo thời gian như thế nào?",
            "analysis_type": "trend",
            "validated_sql": 'SELECT "month", "revenue" FROM "monthly_revenue"',
            "computed_stats": {
                "row_count": 6,
                "metrics": {"total": {"value": 1200, "display_value": "1200"}},
                "data_quality": {"warnings": []},
            },
            "chart_manifest": {"chart_type": "table"},
            "sql_result": {"row_count": 6},
        }
    )

    assert section["semantic_status"] == "warning"
    assert any(
        "lacks an explicit grounded time series" in warning
        for warning in section["semantic_warnings"]
    )


def test_deterministic_critic_flags_missing_recommendations_and_missing_caveats():
    issues = _deterministic_critic_issues(
        {
            "report_sections": [
                {
                    "title": "Price and Survival",
                    "semantic_warnings": [
                        "The SQL uses multiple joins with aggregation."
                    ],
                    "section_confidence": "medium",
                }
            ]
        },
        "# Report\n\n## Price and Survival\n\nGiá vé là yếu tố quyết định khả năng sống sót.",
    )

    assert any("Recommendations" in issue for issue in issues)
    assert any("strong analytical claims" in issue for issue in issues)


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
            return {
                "choices": [{"message": {"content": "SELECT * FROM NonExistentTable"}}]
            }
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

    # Either the pipeline surfaces the failure, or it self-corrects and returns a grounded answer.
    has_error_signal = bool(result.get("errors")) or bool(
        result.get("error_categories")
    )
    recovered_successfully = "66.08" in result.get("answer", "")
    assert has_error_signal or recovered_successfully


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

    # Either the validator failure is surfaced, or the worker self-corrects and succeeds.
    has_error_signal = bool(result.get("errors")) or bool(
        result.get("error_categories")
    )
    recovered_successfully = "66.08" in result.get("answer", "")
    assert has_error_signal or recovered_successfully


def test_v3_sql_exhausted_retries_returns_graceful_error(
    monkeypatch, analytics_db_path
):
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
    has_error_signal = bool(result.get("errors")) or bool(
        result.get("error_categories")
    )
    assert has_error_signal, (
        "Expected errors or error_categories to be populated after exhausted retries, "
        f"got: errors={result.get('errors')}, error_categories={result.get('error_categories')}"
    )
