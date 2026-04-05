from __future__ import annotations

from app.graph.nodes import _ensure_v3_schema_context
from app.tools.validate_sql import validate_sql


def test_ensure_v3_schema_context_builds_xml_without_business_context(analytics_db_path):
    state = {
        "user_query": "Tạo báo cáo",
        "target_db_path": analytics_db_path,
        "table_contexts": {},
    }

    enriched = _ensure_v3_schema_context(state)

    assert enriched.get("schema_context")
    xml_context = enriched.get("xml_database_context", "")
    assert xml_context
    assert "<database_context>" in xml_context
    assert "<table name=" in xml_context
    assert "No business context provided." in xml_context


def test_validate_sql_rejects_unknown_quoted_table_name():
    result = validate_sql('SELECT * FROM "Performance_of_Students"')

    assert result.is_valid is False
    assert any("Unknown table(s): performance_of_students" in reason for reason in result.reasons)
