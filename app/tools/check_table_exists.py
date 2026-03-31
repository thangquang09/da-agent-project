"""Table existence checker for database operations."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def table_exists(db_path: str | Path, table_name: str) -> bool:
    """Check if a table exists in the SQLite database.

    Args:
        db_path: Path to SQLite database file
        table_name: Name of table to check

    Returns:
        True if table exists, False otherwise

    Example:
        >>> table_exists("data/warehouse/analytics.db", "daily_metrics")
        True
    """
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name=?
            """,
            (table_name,),
        )
        return cursor.fetchone() is not None
    finally:
        conn.close()
