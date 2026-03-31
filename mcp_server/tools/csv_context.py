from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import load_settings


def tool_validate_csv(file_path: str) -> dict[str, Any]:
    """
    Validate a CSV file for processing.

    Checks file size, encoding, delimiter, column names, and structure.

    Args:
        file_path: Path to CSV file

    Returns:
        Dict with validation result including:
        - is_valid: bool
        - reasons: list of error messages if invalid
        - detected_encoding: str
        - detected_delimiter: str
        - sanitized_columns: list of cleaned column names
        - estimated_rows: int
    """
    from app.tools.csv_validator import validate_csv

    try:
        result = validate_csv(file_path)
        return {
            "is_valid": result.is_valid,
            "reasons": result.reasons,
            "detected_encoding": result.detected_encoding,
            "detected_delimiter": result.detected_delimiter,
            "sanitized_columns": result.sanitized_columns,
            "estimated_rows": result.estimated_rows,
            "file_size_bytes": result.file_size_bytes,
        }
    except Exception as exc:
        return {
            "is_valid": False,
            "reasons": [f"Validation error: {exc}"],
            "detected_encoding": "",
            "detected_delimiter": "",
            "sanitized_columns": [],
            "estimated_rows": 0,
            "file_size_bytes": 0,
        }


def tool_profile_csv(
    file_path: str,
    table_name: str | None = None,
    encoding: str | None = None,
    delimiter: str | None = None,
) -> dict[str, Any]:
    """
    Profile a CSV file to extract schema and statistics.

    Uses pandas if available, falls back to csv module otherwise.

    Args:
        file_path: Path to CSV file
        table_name: Optional table name (derived from filename if not provided)
        encoding: File encoding (auto-detected if not provided)
        delimiter: CSV delimiter (auto-detected if not provided)

    Returns:
        Dict with profile including:
        - table_name: str
        - columns: list of column profiles
        - row_count: int
        - stats: dict of statistics
        - sample_rows: list of sample data rows
    """
    from app.tools.csv_profiler import profile_csv

    try:
        result = profile_csv(
            file_path=file_path,
            table_name=table_name,
            encoding=encoding,
            delimiter=delimiter,
        )
        return {
            "table_name": result.table_name,
            "columns": [
                {
                    "name": col.name,
                    "dtype": col.dtype,
                    "sample_values": col.sample_values,
                    "null_count": col.null_count,
                    "null_percentage": col.null_percentage,
                    "unique_count": col.unique_count,
                    "min_value": col.min_value,
                    "max_value": col.max_value,
                    "mean": col.mean,
                    "std": col.std,
                }
                for col in result.columns
            ],
            "row_count": result.row_count,
            "stats": result.stats,
            "sample_rows": result.sample_rows[:5],
            "file_size_bytes": result.file_size_bytes,
        }
    except Exception as exc:
        return {
            "table_name": table_name or Path(file_path).stem,
            "columns": [],
            "row_count": 0,
            "stats": {},
            "sample_rows": [],
            "error": str(exc),
        }


def tool_auto_register_csv(
    file_path: str,
    table_name: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """
    Validate, profile, and auto-register a CSV file into SQLite.

    Pipeline:
    1. Validate CSV (file size, encoding, delimiter, etc.)
    2. Profile CSV (extract schema, stats)
    3. Generate CREATE TABLE SQL
    4. Execute CREATE TABLE
    5. Insert data

    Args:
        file_path: Path to CSV file
        table_name: Optional table name (derived from filename if not provided)
        db_path: Path to SQLite database (uses default if not provided)

    Returns:
        Dict with registration result including:
        - table_name: str
        - schema_sql: str
        - row_count: int
        - columns: list of column profiles
        - error: str | None
    """
    from app.tools.auto_register import auto_register_csv

    settings = load_settings()
    if db_path is None:
        db_path = settings.sqlite_db_path

    try:
        result, error = auto_register_csv(
            file_path=file_path,
            db_path=db_path,
            table_name=table_name,
        )
        return {
            "table_name": result.table_name,
            "schema_sql": result.schema_sql,
            "row_count": result.row_count,
            "columns": result.columns,
            "stats": result.stats,
            "validation": {
                "is_valid": result.validation.is_valid,
                "reasons": result.validation.reasons,
                "detected_encoding": result.validation.detected_encoding,
                "detected_delimiter": result.validation.detected_delimiter,
            },
            "error": error,
        }
    except Exception as exc:
        return {
            "table_name": table_name or Path(file_path).stem,
            "schema_sql": "",
            "row_count": 0,
            "columns": [],
            "stats": {},
            "validation": {"is_valid": False, "reasons": [str(exc)]},
            "error": str(exc),
        }
