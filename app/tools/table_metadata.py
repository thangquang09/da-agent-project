from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from app.config import load_settings
from app.logger import logger

_CREATE_TABLE_SQL = """
CREATE SCHEMA IF NOT EXISTS user_data;

CREATE TABLE IF NOT EXISTS user_data.table_contexts (
    table_name VARCHAR PRIMARY KEY,
    business_context TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
"""


def _ensure_table() -> None:
    """Create user_data.table_contexts if it doesn't exist."""
    settings = load_settings()
    with psycopg.connect(settings.database_url) as conn:
        conn.execute(_CREATE_TABLE_SQL)


def get_table_context(table_name: str) -> str:
    """Get business context for a single table. Returns empty string if not found."""
    _ensure_table()
    settings = load_settings()
    with psycopg.connect(settings.database_url) as conn:
        conn.row_factory = dict_row
        cur = conn.execute(
            "SELECT business_context FROM user_data.table_contexts WHERE table_name = %s",
            (table_name,),
        )
        row = cur.fetchone()
        return row["business_context"] if row else ""


def set_table_context(table_name: str, context: str) -> None:
    """Upsert business context for a table."""
    _ensure_table()
    settings = load_settings()
    with psycopg.connect(settings.database_url) as conn:
        conn.execute(
            """
            INSERT INTO user_data.table_contexts (table_name, business_context, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (table_name)
            DO UPDATE SET business_context = EXCLUDED.business_context, updated_at = NOW()
            """,
            (table_name, context),
        )
    logger.info(
        "Saved context for table={table} ({len} chars)",
        table=table_name,
        len=len(context),
    )


def get_all_table_contexts() -> dict[str, str]:
    """Get all table contexts as a dict. Returns {table_name: business_context}."""
    _ensure_table()
    settings = load_settings()
    with psycopg.connect(settings.database_url) as conn:
        conn.row_factory = dict_row
        cur = conn.execute("SELECT table_name, business_context FROM user_data.table_contexts")
        return {row["table_name"]: row["business_context"] for row in cur.fetchall()}


def delete_table_context(table_name: str) -> None:
    """Remove context entry for a table (call when table is dropped)."""
    _ensure_table()
    settings = load_settings()
    with psycopg.connect(settings.database_url) as conn:
        conn.execute(
            "DELETE FROM user_data.table_contexts WHERE table_name = %s",
            (table_name,),
        )
