from __future__ import annotations

from app.tools import get_schema_overview, query_sql, validate_sql


def test_validate_sql_accepts_read_only_query():
    result = validate_sql("SELECT date, dau FROM daily_metrics ORDER BY date DESC LIMIT 3")
    assert result.is_valid is True
    assert result.reasons == []
    assert "daily_metrics" in result.detected_tables


def test_validate_sql_rejects_write_statement():
    result = validate_sql("UPDATE daily_metrics SET dau=1")
    assert result.is_valid is False
    assert any("Only SELECT/CTE" in r for r in result.reasons)
    assert any("Forbidden SQL keyword detected: UPDATE" in r for r in result.reasons)


def test_validate_sql_rejects_unknown_table():
    result = validate_sql("SELECT * FROM unknown_table")
    assert result.is_valid is False
    assert any("Unknown table(s): unknown_table" in r for r in result.reasons)


def test_query_sql_returns_rows_columns_and_latency():
    result = query_sql("SELECT title, retention_rate FROM videos ORDER BY retention_rate DESC LIMIT 2")
    assert result["row_count"] == 2
    assert "title" in result["columns"]
    assert "retention_rate" in result["columns"]
    assert isinstance(result["latency_ms"], float)


def test_get_schema_overview_contains_expected_tables():
    overview = get_schema_overview()
    names = {t["table_name"] for t in overview["tables"]}
    assert {"daily_metrics", "videos", "metric_definitions"}.issubset(names)

