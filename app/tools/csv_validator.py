from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path

from app.logger import logger

MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_ENCODINGS = ["utf-8", "utf-8-sig", "latin-1", "iso-8859-1", "cp1252"]
ALLOWED_DELIMITERS = [",", ";", "\t", "|"]


@dataclass(frozen=True)
class CSVValidationResult:
    is_valid: bool
    reasons: list[str]
    detected_encoding: str
    detected_delimiter: str
    sanitized_columns: list[str]
    estimated_rows: int
    file_size_bytes: int


def _detect_encoding(file_path: Path, sample_bytes: int = 10000) -> str:
    """Detect file encoding by trying common encodings."""
    with open(file_path, "rb") as f:
        raw = f.read(sample_bytes)

    for encoding in ALLOWED_ENCODINGS:
        try:
            raw.decode(encoding)
            return encoding
        except (UnicodeDecodeError, UnicodeError):
            continue

    return "utf-8"


def _detect_delimiter(file_path: Path, encoding: str, sample_lines: int = 10) -> str:
    """Detect CSV delimiter by analyzing first few lines."""
    with open(file_path, encoding=encoding) as f:
        lines = [f.readline() for _ in range(sample_lines)]

    if not lines or not lines[0].strip():
        return ","

    delimiter_counts: dict[str, list[int]] = {d: [] for d in ALLOWED_DELIMITERS}

    for line in lines:
        if not line.strip():
            continue
        for delim in ALLOWED_DELIMITERS:
            delimiter_counts[delim].append(line.count(delim))

    best_delimiter = ","
    best_variance = float("inf")
    best_count = 0

    for delim, counts in delimiter_counts.items():
        if not counts:
            continue
        avg = sum(counts) / len(counts)
        variance = sum((c - avg) ** 2 for c in counts) / len(counts)
        if avg > 0 and variance < best_variance:
            if avg > best_count or (avg == best_count and variance < best_variance):
                best_delimiter = delim
                best_variance = variance
                best_count = int(avg)

    return best_delimiter


def _sanitize_column_name(name: str) -> str:
    """Sanitize column name for SQL compatibility."""
    sanitized = name.strip()
    sanitized = "".join(c if c.isalnum() or c == "_" else "_" for c in sanitized)
    sanitized = sanitized.lower()
    if sanitized and sanitized[0].isdigit():
        sanitized = "col_" + sanitized
    if not sanitized:
        sanitized = "unnamed_column"
    return sanitized


def _estimate_row_count(file_path: Path, encoding: str) -> int:
    """Estimate row count by counting newlines."""
    try:
        with open(file_path, encoding=encoding) as f:
            row_count = sum(1 for _ in f) - 1
        return max(0, row_count)
    except Exception:
        return 0


def validate_csv(file_path: str | Path) -> CSVValidationResult:
    """
    Validate a CSV file for processing.

    Checks:
    1. File exists and readable
    2. File size within limit
    3. Encoding detection
    4. Delimiter detection
    5. Column name sanitization
    6. Basic structure validation

    Returns:
        CSVValidationResult with validation status and metadata.
    """
    file_path = Path(file_path)
    reasons: list[str] = []

    if not file_path.exists():
        return CSVValidationResult(
            is_valid=False,
            reasons=[f"File not found: {file_path}"],
            detected_encoding="",
            detected_delimiter="",
            sanitized_columns=[],
            estimated_rows=0,
            file_size_bytes=0,
        )

    file_size_bytes = file_path.stat().st_size
    if file_size_bytes > MAX_FILE_SIZE_BYTES:
        reasons.append(
            f"File too large: {file_size_bytes / (1024 * 1024):.1f}MB > {MAX_FILE_SIZE_MB}MB limit"
        )

    detected_encoding = _detect_encoding(file_path)
    detected_delimiter = _detect_delimiter(file_path, detected_encoding)
    estimated_rows = _estimate_row_count(file_path, detected_encoding)

    sanitized_columns: list[str] = []
    try:
        with open(file_path, encoding=detected_encoding, newline="") as f:
            reader = csv.reader(f, delimiter=detected_delimiter)
            try:
                header = next(reader)
                sanitized_columns = [_sanitize_column_name(col) for col in header]
                if not header or all(not col.strip() for col in header):
                    reasons.append("Empty or invalid header row")
            except StopIteration:
                reasons.append("File appears to be empty")
    except Exception as exc:
        reasons.append(f"Failed to read file: {exc}")

    if estimated_rows < 1:
        reasons.append("File has no data rows")

    is_valid = len(reasons) == 0

    logger.info(
        "CSV validation: valid={valid}, encoding={enc}, delimiter={delim}, "
        "cols={cols}, rows={rows}, reasons={reasons}",
        valid=is_valid,
        enc=detected_encoding,
        delim=repr(detected_delimiter),
        cols=len(sanitized_columns),
        rows=estimated_rows,
        reasons=reasons,
    )

    return CSVValidationResult(
        is_valid=is_valid,
        reasons=reasons,
        detected_encoding=detected_encoding,
        detected_delimiter=detected_delimiter,
        sanitized_columns=sanitized_columns,
        estimated_rows=estimated_rows,
        file_size_bytes=file_size_bytes,
    )
