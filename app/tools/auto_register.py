from __future__ import annotations

import csv
import dataclasses
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.logger import logger
from app.tools.csv_profiler import CSVProfileResult, generate_schema_sql, profile_csv
from app.tools.csv_validator import CSVValidationResult, validate_csv


@dataclass(frozen=True)
class AutoRegisterResult:
    table_name: str
    schema_sql: str
    row_count: int
    columns: list[dict[str, Any]]
    semantic_description: str | None
    stats: dict[str, Any]
    validation: CSVValidationResult


def auto_register_csv(
    file_path: str | Path,
    db_path: str | Path,
    table_name: str | None = None,
    semantic_description: str | None = None,
) -> tuple[AutoRegisterResult, str | None]:
    """
    Validate, profile, and auto-register a CSV file into SQLite database.

    Pipeline:
    1. Validate CSV (file size, encoding, delimiter, etc.)
    2. Profile CSV (extract schema, stats)
    3. Generate CREATE TABLE SQL
    4. Execute CREATE TABLE
    5. Insert data

    Args:
        file_path: Path to CSV file
        db_path: Path to SQLite database
        table_name: Optional table name (derived from filename if not provided)
        semantic_description: Optional semantic description from LLM

    Returns:
        Tuple of (AutoRegisterResult, error_message if any)
    """
    file_path = Path(file_path)
    db_path = Path(db_path)

    validation = validate_csv(file_path)
    if not validation.is_valid:
        return (
            AutoRegisterResult(
                table_name=table_name or file_path.stem,
                schema_sql="",
                row_count=0,
                columns=[],
                semantic_description=None,
                stats={},
                validation=validation,
            ),
            f"Validation failed: {'; '.join(validation.reasons)}",
        )

    try:
        profile = profile_csv(
            file_path=file_path,
            table_name=table_name,
            encoding=validation.detected_encoding,
            delimiter=validation.detected_delimiter,
        )
    except Exception as exc:
        return (
            AutoRegisterResult(
                table_name=table_name or file_path.stem,
                schema_sql="",
                row_count=0,
                columns=[],
                semantic_description=None,
                stats={},
                validation=validation,
            ),
            f"Profiling failed: {exc}",
        )

    schema_sql = generate_schema_sql(profile)

    try:
        _execute_create_table(db_path, schema_sql, profile, validation)
    except Exception as exc:
        logger.error("Failed to create table: {exc}", exc=exc)
        return (
            AutoRegisterResult(
                table_name=profile.table_name,
                schema_sql=schema_sql,
                row_count=profile.row_count,
                columns=[vars(col) for col in profile.columns],
                semantic_description=semantic_description,
                stats=profile.stats,
                validation=validation,
            ),
            f"Failed to create table: {exc}",
        )

    logger.info(
        "Auto-registered CSV: table={table}, db={db}, rows={rows}",
        table=profile.table_name,
        db=db_path,
        rows=profile.row_count,
    )

    return (
        AutoRegisterResult(
            table_name=profile.table_name,
            schema_sql=schema_sql,
            row_count=profile.row_count,
            columns=[vars(col) for col in profile.columns],
            semantic_description=semantic_description,
            stats=profile.stats,
            validation=validation,
        ),
        None,
    )


def _execute_create_table(
    db_path: Path,
    schema_sql: str,
    profile: CSVProfileResult,
    validation: CSVValidationResult,
) -> None:
    """Execute CREATE TABLE and insert data."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    try:
        quoted_table = profile.table_name.replace('"', '""')
        cursor.execute(f'DROP TABLE IF EXISTS "{quoted_table}"')
        cursor.execute(schema_sql)

        insert_sql = _generate_insert_sql(profile)
        with open(
            validation.file_path, encoding=validation.detected_encoding, newline=""
        ) as f:
            import csv

            reader = csv.DictReader(f, delimiter=validation.detected_delimiter)
            batch = []
            for row in reader:
                values = [row.get(col.name) for col in profile.columns]
                batch.append(values)
                if len(batch) >= 1000:
                    cursor.executemany(insert_sql, batch)
                    batch = []
            if batch:
                cursor.executemany(insert_sql, batch)

        conn.commit()
    finally:
        conn.close()


def _generate_insert_sql(profile: CSVProfileResult) -> str:
    """Generate INSERT SQL statement."""
    quoted_table = profile.table_name.replace('"', '""')
    columns = ", ".join(f'"{col.name.replace(chr(34), chr(34)*2)}"' for col in profile.columns)
    placeholders = ", ".join("?" for _ in profile.columns)
    return f'INSERT INTO "{quoted_table}" ({columns}) VALUES ({placeholders})'
