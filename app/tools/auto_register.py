from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.config import load_settings
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


def _get_postgres_connection():
    """Get PostgreSQL connection from settings."""
    settings = load_settings()
    return psycopg.connect(settings.database_url)


def auto_register_csv(
    file_path: str | Path,
    table_name: str | None = None,
    semantic_description: str | None = None,
) -> tuple[AutoRegisterResult, str | None]:
    """
    Validate, profile, and auto-register a CSV file into PostgreSQL database.

    Pipeline:
    1. Validate CSV (file size, encoding, delimiter, etc.)
    2. Profile CSV (extract schema, stats)
    3. Generate CREATE TABLE SQL
    4. Execute CREATE TABLE
    5. Insert data

    Args:
        file_path: Path to CSV file
        table_name: Optional table name (derived from filename if not provided)
        semantic_description: Optional semantic description from LLM

    Returns:
        Tuple of (AutoRegisterResult, error_message if any)
    """
    file_path = Path(file_path)

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
        _execute_create_table(profile, validation)
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
        "Auto-registered CSV: table={table}, rows={rows}",
        table=profile.table_name,
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
    profile: CSVProfileResult,
    validation: CSVValidationResult,
) -> None:
    """Execute CREATE TABLE and insert data into PostgreSQL."""
    with _get_postgres_connection() as conn:
        # Use dict_row factory for consistent result formatting
        conn.row_factory = dict_row

        with conn.cursor() as cur:
            # Drop table if exists (for re-upload scenarios)
            safe_table = _quote_identifier(profile.table_name)
            cur.execute(f'DROP TABLE IF EXISTS {safe_table}')

            # Create table with PostgreSQL-compatible types
            pg_schema_sql = _convert_sqlite_to_postgres_schema(profile)
            cur.execute(pg_schema_sql)

            # Insert data in batches
            insert_sql = _generate_postgres_insert_sql(profile)

            with open(
                validation.file_path, encoding=validation.detected_encoding, newline=""
            ) as f:
                reader = csv.DictReader(f, delimiter=validation.detected_delimiter)
                batch = []
                for row in reader:
                    # Convert values to appropriate Python types
                    values = _convert_row_values(row, profile)
                    batch.append(values)
                    if len(batch) >= 1000:
                        cur.executemany(insert_sql, batch)
                        batch = []
                if batch:
                    cur.executemany(insert_sql, batch)

        # Auto-commit on successful exit from with block


def _quote_identifier(name: str) -> str:
    """Quote SQL identifier for PostgreSQL."""
    # Double any double-quotes in the name and wrap in double-quotes
    quoted = name.replace('"', '""')
    return f'"{quoted}"'


def _convert_sqlite_to_postgres_schema(profile: CSVProfileResult) -> str:
    """Convert SQLite schema SQL to PostgreSQL-compatible SQL."""
    # PostgreSQL type mapping
    pg_type_map = {
        "integer": "INTEGER",
        "float": "DOUBLE PRECISION",  # More precise than REAL
        "datetime": "TIMESTAMPTZ",    # PostgreSQL timezone-aware timestamp
        "text": "TEXT",
    }

    columns_sql = []
    for col in profile.columns:
        pg_type = pg_type_map.get(col.dtype, "TEXT")
        # Handle nullable columns explicitly
        nullable_clause = "" if col.null_count == 0 else "NULL"
        quoted_col = _quote_identifier(col.name)
        columns_sql.append(f"    {quoted_col} {pg_type} {nullable_clause}")

    quoted_table = _quote_identifier(profile.table_name)
    columns_str = ",\n".join(columns_sql)
    return f"CREATE TABLE {quoted_table} (\n{columns_str}\n);"


def _generate_postgres_insert_sql(profile: CSVProfileResult) -> str:
    """Generate INSERT SQL statement for PostgreSQL."""
    quoted_table = _quote_identifier(profile.table_name)
    columns = ", ".join(_quote_identifier(col.name) for col in profile.columns)
    # PostgreSQL uses %s for parameter placeholders (not ?)
    placeholders = ", ".join("%s" for _ in profile.columns)
    return f"INSERT INTO {quoted_table} ({columns}) VALUES ({placeholders})"


def _convert_row_values(row: dict[str, str], profile: CSVProfileResult) -> list[Any]:
    """Convert string values from CSV to appropriate Python types for PostgreSQL."""
    values = []

    for col in profile.columns:
        raw_value = row.get(col.name)

        # Handle NULL/empty values
        if raw_value is None or str(raw_value).strip() == "":
            values.append(None)
            continue

        # Convert based on detected dtype
        if col.dtype == "integer":
            try:
                # Remove commas from numbers (e.g., "1,234" -> 1234)
                clean_value = str(raw_value).replace(",", "")
                values.append(int(clean_value))
            except (ValueError, TypeError):
                values.append(None)
        elif col.dtype == "float":
            try:
                clean_value = str(raw_value).replace(",", "")
                values.append(float(clean_value))
            except (ValueError, TypeError):
                values.append(None)
        elif col.dtype == "datetime":
            try:
                # Parse ISO datetime strings
                dt = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
                values.append(dt)
            except (ValueError, TypeError):
                # Fall back to string if parsing fails
                values.append(str(raw_value))
        else:
            # Text type - keep as string
            values.append(str(raw_value))

    return values
