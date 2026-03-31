from __future__ import annotations

from app.tools import dataset_context, get_schema_overview, query_sql, validate_sql


def test_validate_sql_accepts_read_only_query():
    result = validate_sql(
        "SELECT date, dau FROM daily_metrics ORDER BY date DESC LIMIT 3"
    )
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


def test_validate_sql_allows_cte_name_as_table_reference():
    result = validate_sql(
        """
        WITH tmp AS (SELECT date, dau FROM daily_metrics)
        SELECT * FROM tmp
        """
    )
    assert result.is_valid is True


def test_validate_sql_allows_multiple_ctes():
    """Test that chained CTEs (comma-separated) are properly recognized."""
    result = validate_sql(
        """
        WITH 
            daily_stats AS (SELECT date, COUNT(*) as users FROM daily_metrics GROUP BY date),
            trends AS (SELECT *, LAG(users) OVER (ORDER BY date) as prev_users FROM daily_stats)
        SELECT * FROM trends WHERE users > prev_users * 1.1
        """
    )
    assert result.is_valid is True, f"Expected valid but got reasons: {result.reasons}"
    assert "daily_stats" in result.detected_tables or "trends" in result.detected_tables


def test_validate_sql_allows_recursive_cte():
    """Test that recursive CTEs with WITH RECURSIVE are properly validated."""
    # Using videos table for the recursive CTE test
    result = validate_sql(
        """
        WITH RECURSIVE video_series AS (
            SELECT video_id, title, publish_date FROM videos WHERE title LIKE 'Intro%'
            UNION ALL
            SELECT v.video_id, v.title, v.publish_date 
            FROM videos v
            JOIN video_series vs ON v.publish_date > vs.publish_date
            LIMIT 10
        )
        SELECT * FROM video_series
        """
    )
    assert result.is_valid is True, f"Expected valid but got reasons: {result.reasons}"
    assert "video_series" in result.detected_tables


def test_validate_sql_allows_cte_referencing_previous_cte():
    """Test CTEs that reference other CTEs are properly validated."""
    result = validate_sql(
        """
        WITH 
            base_data AS (
                SELECT video_id, title, views FROM videos WHERE views > 1000
            ),
            ranked_data AS (
                SELECT *, ROW_NUMBER() OVER (ORDER BY views DESC) as rank
                FROM base_data
            )
        SELECT * FROM ranked_data WHERE rank <= 10
        """
    )
    assert result.is_valid is True, f"Expected valid but got reasons: {result.reasons}"


def test_validate_sql_allows_complex_nested_cte():
    """Test deeply nested CTE structures."""
    result = validate_sql(
        """
        WITH 
            weekly_metrics AS (
                SELECT 
                    strftime('%Y-W%W', date) as week,
                    AVG(dau) as avg_dau,
                    SUM(revenue) as total_revenue
                FROM daily_metrics
                GROUP BY week
            ),
            weekly_comparison AS (
                SELECT 
                    week,
                    avg_dau,
                    total_revenue,
                    LAG(avg_dau) OVER (ORDER BY week) as prev_avg_dau,
                    LAG(total_revenue) OVER (ORDER BY week) as prev_revenue
                FROM weekly_metrics
            ),
            final_stats AS (
                SELECT 
                    week,
                    avg_dau,
                    total_revenue,
                    CASE 
                        WHEN prev_avg_dau > 0 THEN ((avg_dau - prev_avg_dau) / prev_avg_dau * 100)
                        ELSE 0 
                    END as dau_growth_pct
                FROM weekly_comparison
            )
        SELECT * FROM final_stats ORDER BY week DESC LIMIT 5
        """
    )
    assert result.is_valid is True, f"Expected valid but got reasons: {result.reasons}"


def test_validate_sql_injects_limit_when_missing():
    result = validate_sql(
        "SELECT date, dau FROM daily_metrics ORDER BY date DESC",
        max_limit=7,
    )
    assert result.is_valid is True
    assert "LIMIT 7" in result.sanitized_sql.upper()


def test_query_sql_returns_rows_columns_and_latency():
    result = query_sql(
        "SELECT title, retention_rate FROM videos ORDER BY retention_rate DESC LIMIT 2"
    )
    assert result["row_count"] == 2
    assert "title" in result["columns"]
    assert "retention_rate" in result["columns"]
    assert isinstance(result["latency_ms"], float)


def test_get_schema_overview_contains_expected_tables():
    overview = get_schema_overview()
    names = {t["table_name"] for t in overview["tables"]}
    assert {"daily_metrics", "videos", "metric_definitions"}.issubset(names)
