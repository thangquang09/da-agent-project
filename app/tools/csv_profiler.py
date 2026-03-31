from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.logger import logger

try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    pd = None


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    dtype: str
    sample_values: list[Any]
    null_count: int
    null_percentage: float
    unique_count: int | None
    min_value: Any | None
    max_value: Any | None
    mean: float | None
    std: float | None


@dataclass(frozen=True)
class CSVProfileResult:
    table_name: str
    columns: list[ColumnProfile]
    row_count: int
    stats: dict[str, Any]
    sample_rows: list[dict[str, Any]]
    file_size_bytes: int


def _infer_dtype(values: list[Any]) -> str:
    """Infer column dtype from sample values."""
    non_null = [v for v in values if v is not None and str(v).strip() != ""]
    if not non_null:
        return "text"

    try:
        for v in non_null[:10]:
            int(str(v).replace(",", ""))
        return "integer"
    except (ValueError, TypeError):
        pass

    try:
        for v in non_null[:10]:
            float(str(v).replace(",", ""))
        return "float"
    except (ValueError, TypeError):
        pass

    try:
        for v in non_null[:10]:
            datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return "datetime"
    except (ValueError, TypeError):
        pass

    return "text"


def profile_csv(
    file_path: str | Path,
    table_name: str | None = None,
    encoding: str | None = None,
    delimiter: str | None = None,
    sample_rows: int = 100,
    max_rows: int = 10000,
) -> CSVProfileResult:
    """
    Profile a CSV file to extract schema and statistics.

    Uses pandas if available, falls back to csv module otherwise.

    Args:
        file_path: Path to CSV file
        table_name: Optional table name (derived from filename if not provided)
        encoding: File encoding (auto-detected if not provided)
        delimiter: CSV delimiter (auto-detected if not provided)
        sample_rows: Number of rows to sample for statistics
        max_rows: Maximum rows to read for profiling

    Returns:
        CSVProfileResult with schema and statistics.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if table_name is None:
        table_name = file_path.stem.lower().replace(" ", "_").replace("-", "_")

    file_size_bytes = file_path.stat().st_size

    encoding = encoding or "utf-8"
    delimiter = delimiter or ","

    if PANDAS_AVAILABLE and pd is not None:
        return _profile_with_pandas(
            file_path,
            table_name,
            encoding,
            delimiter,
            sample_rows,
            max_rows,
            file_size_bytes,
        )

    return _profile_with_csv(
        file_path, table_name, encoding, delimiter, sample_rows, file_size_bytes
    )


def _profile_with_pandas(
    file_path: Path,
    table_name: str,
    encoding: str,
    delimiter: str,
    sample_rows: int,
    max_rows: int,
    file_size_bytes: int,
) -> CSVProfileResult:
    """Profile CSV using pandas (faster, more accurate)."""
    df = pd.read_csv(
        file_path,
        encoding=encoding,
        delimiter=delimiter,
        nrows=max_rows,
    )

    row_count = len(df)
    columns: list[ColumnProfile] = []

    for col in df.columns:
        col_data = df[col]
        non_null = col_data.dropna()
        sample_vals = non_null.head(5).tolist()

        unique_count = col_data.nunique() if row_count > 0 else 0
        null_count = col_data.isna().sum()
        null_pct = (null_count / row_count * 100) if row_count > 0 else 0

        dtype = str(col_data.dtype)
        if "int" in dtype:
            dtype = "integer"
        elif "float" in dtype:
            dtype = "float"
        elif "datetime" in dtype or "date" in dtype:
            dtype = "datetime"
        else:
            dtype = _infer_dtype(sample_vals)

        min_val = None
        max_val = None
        mean_val = None
        std_val = None

        if len(non_null) > 0 and dtype in ("integer", "float"):
            try:
                numeric = pd.to_numeric(non_null, errors="coerce")
                min_val = float(numeric.min())
                max_val = float(numeric.max())
                mean_val = float(numeric.mean())
                std_val = float(numeric.std())
            except (ValueError, TypeError):
                pass

        columns.append(
            ColumnProfile(
                name=col,
                dtype=dtype,
                sample_values=sample_vals,
                null_count=int(null_count),
                null_percentage=round(null_pct, 2),
                unique_count=int(unique_count),
                min_value=min_val,
                max_value=max_val,
                mean=mean_val,
                std=std_val,
            )
        )

    stats = {
        "total_rows": row_count,
        "total_columns": len(columns),
        "memory_usage_bytes": int(df.memory_usage(deep=True).sum()),
    }

    sample_rows_data = df.head(sample_rows).to_dict(orient="records")

    logger.info(
        "CSV profiled with pandas: table={table}, cols={cols}, rows={rows}",
        table=table_name,
        cols=len(columns),
        rows=row_count,
    )

    return CSVProfileResult(
        table_name=table_name,
        columns=columns,
        row_count=row_count,
        stats=stats,
        sample_rows=sample_rows_data,
        file_size_bytes=file_size_bytes,
    )


def _profile_with_csv(
    file_path: Path,
    table_name: str,
    encoding: str,
    delimiter: str,
    sample_rows: int,
    file_size_bytes: int,
) -> CSVProfileResult:
    """Profile CSV using standard csv module (fallback)."""
    with open(file_path, encoding=encoding, newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        headers = reader.fieldnames or []
        all_rows = list(reader)

    row_count = len(all_rows)
    columns: list[ColumnProfile] = []

    for col in headers:
        values = [row.get(col) for row in all_rows]
        non_null = [v for v in values if v is not None and str(v).strip() != ""]
        sample_vals = non_null[:5]

        unique_count = len(set(non_null)) if non_null else 0
        null_count = len(values) - len(non_null)
        null_pct = (null_count / len(values) * 100) if values else 0

        dtype = _infer_dtype(sample_vals)

        columns.append(
            ColumnProfile(
                name=col,
                dtype=dtype,
                sample_values=sample_vals,
                null_count=null_count,
                null_percentage=round(null_pct, 2),
                unique_count=unique_count,
                min_value=None,
                max_value=None,
                mean=None,
                std=None,
            )
        )

    stats = {
        "total_rows": row_count,
        "total_columns": len(columns),
    }

    sample_rows_data = all_rows[:sample_rows]

    logger.info(
        "CSV profiled with csv module: table={table}, cols={cols}, rows={rows}",
        table=table_name,
        cols=len(columns),
        rows=row_count,
    )

    return CSVProfileResult(
        table_name=table_name,
        columns=columns,
        row_count=row_count,
        stats=stats,
        sample_rows=sample_rows_data,
        file_size_bytes=file_size_bytes,
    )


def generate_schema_sql(profile: CSVProfileResult) -> str:
    """Generate CREATE TABLE SQL from CSV profile."""
    sql_type_map = {
        "integer": "INTEGER",
        "float": "REAL",
        "datetime": "TEXT",
        "text": "TEXT",
    }

    columns_sql = []
    for col in profile.columns:
        sql_type = sql_type_map.get(col.dtype, "TEXT")
        columns_sql.append(f"    {col.name} {sql_type}")

    return f"CREATE TABLE {profile.table_name} (\n" + ",\n".join(columns_sql) + "\n);"
