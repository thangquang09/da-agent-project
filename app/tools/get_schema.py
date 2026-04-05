from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re

import psycopg
from psycopg.rows import dict_row

from app.config import load_settings
from app.logger import logger


VALID_TABLE_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    col_type: str
    nullable: bool
    is_pk: bool


def _list_tables_postgres() -> list[str]:
    """List all tables in PostgreSQL database."""
    settings = load_settings()
    with psycopg.connect(settings.database_url) as conn:
        conn.row_factory = dict_row
        cur = conn.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        )
        tables = [row["table_name"] for row in cur.fetchall()]
    logger.info("Discovered {count} tables from PostgreSQL", count=len(tables))
    return tables


def _list_tables_sqlite(db_path: Path) -> list[str]:
    """List all tables in SQLite database."""
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
    tables = [row[0] for row in rows]
    logger.info("Discovered {count} tables from {path}", count=len(tables), path=db_path)
    return tables


def list_tables(db_path: Path | None = None) -> list[str]:
    """List all tables in the database.

    Args:
        db_path: Optional database path.
            - If Path to .sqlite/.db file: uses SQLite
            - If None: uses PostgreSQL (default)

    Returns:
        List of table names.
    """
    if db_path:
        return _list_tables_sqlite(db_path)
    else:
        return _list_tables_postgres()


def _describe_table_postgres(table_name: str) -> list[ColumnInfo]:
    """Describe table schema in PostgreSQL database."""
    if not VALID_TABLE_NAME_PATTERN.match(table_name):
        raise ValueError(f"Invalid table name: {table_name}")

    settings = load_settings()
    with psycopg.connect(settings.database_url) as conn:
        conn.row_factory = dict_row
        cur = conn.execute(
            """
            SELECT
                columns.column_name,
                columns.data_type,
                columns.is_nullable,
                CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END as is_pk
            FROM information_schema.columns AS columns
            LEFT JOIN (
                SELECT a.attname AS column_name
                FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid
                    AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = (
                    SELECT oid FROM pg_class WHERE relname = %s AND relnamespace = 'public'::regnamespace
                )
                AND i.indisprimary
            ) pk ON pk.column_name = columns.column_name
            WHERE columns.table_schema = 'public'
            AND columns.table_name = %s
            ORDER BY columns.ordinal_position
            """,
            (table_name, table_name),
        )
        columns = [
            ColumnInfo(
                name=row["column_name"],
                col_type=row["data_type"],
                nullable=row["is_nullable"] == "YES",
                is_pk=row["is_pk"],
            )
            for row in cur.fetchall()
        ]
    logger.info(
        "Described table {table_name} with {count} columns",
        table_name=table_name,
        count=len(columns),
    )
    return columns


def _describe_table_sqlite(table_name: str, db_path: Path) -> list[ColumnInfo]:
    """Describe table schema in SQLite database."""
    if not VALID_TABLE_NAME_PATTERN.match(table_name):
        raise ValueError(f"Invalid table name: {table_name}")

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    columns = [
        ColumnInfo(
            name=row[1],
            col_type=row[2],
            nullable=row[3] == 0,
            is_pk=row[5] == 1,
        )
        for row in rows
    ]
    logger.info(
        "Described table {table_name} with {count} columns",
        table_name=table_name,
        count=len(columns),
    )
    return columns


def describe_table(table_name: str, db_path: Path | None = None) -> list[ColumnInfo]:
    """Describe table schema in the database.

    Args:
        table_name: Name of table to describe
        db_path: Optional database path.
            - If Path to .sqlite/.db file: uses SQLite
            - If None: uses PostgreSQL (default)

    Returns:
        List of ColumnInfo objects with column metadata.
    """
    if db_path:
        return _describe_table_sqlite(table_name, db_path)
    else:
        return _describe_table_postgres(table_name)


def get_schema_overview(db_path: Path | None = None) -> dict[str, Any]:
    """Get complete schema overview for all tables.

    Args:
        db_path: Optional database path (None for PostgreSQL)

    Returns:
        Dictionary with tables and their column information.
    """
    tables = list_tables(db_path=db_path)
    return {
        "tables": [
            {
                "table_name": table,
                "columns": [
                    {
                        "name": col.name,
                        "type": col.col_type,
                        "nullable": col.nullable,
                        "is_primary_key": col.is_pk,
                    }
                    for col in describe_table(table, db_path=db_path)
                ],
            }
            for table in tables
        ]
    }
