"""Tests for Phase 1.1: Schema isolation migration.

Verifies that the migration creates `agent` and `user_data` schemas
and that the migration runner executes cleanly.
"""

from __future__ import annotations

import psycopg

from app.config import load_settings


def _get_conn():
    settings = load_settings()
    return psycopg.connect(settings.database_url)


def test_migration_creates_agent_schema():
    """Migration 002 must create `agent` schema."""
    from data.migrations import create_schemas

    create_schemas.run()

    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'agent'"
        ).fetchall()
    assert len(rows) == 1


def test_migration_creates_user_data_schema():
    """Migration 002 must create `user_data` schema."""
    from data.migrations import create_schemas

    create_schemas.run()

    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'user_data'"
        ).fetchall()
    assert len(rows) == 1


def test_migration_is_idempotent():
    """Running migration twice must not raise."""
    from data.migrations import create_schemas

    create_schemas.run()  # First run
    create_schemas.run()  # Second run — should succeed silently


def test_agent_schema_tables_can_be_created():
    """Can create tables in agent schema."""
    from data.migrations import create_schemas

    create_schemas.run()

    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent._test_table (
                id SERIAL PRIMARY KEY,
                data TEXT
            )
        """)
        conn.execute("INSERT INTO agent._test_table (data) VALUES (%s)", ("hello",))
        row = conn.execute("SELECT data FROM agent._test_table LIMIT 1").fetchone()
        conn.execute("DROP TABLE IF EXISTS agent._test_table")
    assert row[0] == "hello"


def test_user_data_schema_tables_can_be_created():
    """Can create tables in user_data schema."""
    from data.migrations import create_schemas

    create_schemas.run()

    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_data._test_upload (
                id SERIAL PRIMARY KEY,
                content TEXT
            )
        """)
        conn.execute("INSERT INTO user_data._test_upload (content) VALUES (%s)", ("csv-data",))
        row = conn.execute("SELECT content FROM user_data._test_upload LIMIT 1").fetchone()
        conn.execute("DROP TABLE IF EXISTS user_data._test_upload")
    assert row[0] == "csv-data"
