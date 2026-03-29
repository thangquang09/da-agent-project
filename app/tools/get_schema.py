from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re

from app.config import load_settings
from app.logger import logger


VALID_TABLE_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    col_type: str
    nullable: bool
    is_pk: bool


def _default_db_path() -> Path:
    return Path(load_settings().sqlite_db_path)


def list_tables(db_path: Path | None = None) -> list[str]:
    path = db_path or _default_db_path()
    with sqlite3.connect(path) as conn:
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
    logger.info("Discovered {count} tables from {path}", count=len(tables), path=path)
    return tables


def describe_table(table_name: str, db_path: Path | None = None) -> list[ColumnInfo]:
    if not VALID_TABLE_NAME_PATTERN.match(table_name):
        raise ValueError(f"Invalid table name: {table_name}")

    path = db_path or _default_db_path()
    with sqlite3.connect(path) as conn:
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


def get_schema_overview(db_path: Path | None = None) -> dict[str, Any]:
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
