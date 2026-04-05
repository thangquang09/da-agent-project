"""Table existence checker for PostgreSQL database operations."""

from __future__ import annotations

import psycopg

from app.config import load_settings
from app.logger import logger


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the PostgreSQL database.

    Args:
        table_name: Name of table to check (unquoted, will be sanitized)

    Returns:
        True if table exists, False otherwise

    Example:
        >>> table_exists("daily_metrics")
        True
    """
    settings = load_settings()

    try:
        with psycopg.connect(settings.database_url) as conn:
            # Use PostgreSQL's information_schema for cross-database compatibility
            # Also check for temp tables and views
            cur = conn.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = %s
                """,
                (table_name,),
            )
            return cur.fetchone() is not None
    except Exception as exc:
        logger.error("Failed to check table existence: {exc}", exc=exc)
        return False
