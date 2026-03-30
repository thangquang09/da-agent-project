from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import load_settings
from app.logger import logger


FORBIDDEN_SQL_PATTERNS = [
    r"\bINSERT\b",
    r"\bUPDATE\b",
    r"\bDELETE\b",
    r"\bDROP\b",
    r"\bALTER\b",
    r"\bTRUNCATE\b",
    r"\bCREATE\b",
    r"\bREPLACE\b",
    r"\bATTACH\b",
    r"\bDETACH\b",
    r"\bPRAGMA\b",
]
READ_QUERY_PATTERN = re.compile(r"^\s*(SELECT|WITH)\b", flags=re.IGNORECASE | re.DOTALL)
TABLE_TOKEN_PATTERN = re.compile(r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)\b", flags=re.IGNORECASE)
CTE_NAME_PATTERN = re.compile(r"with\s+([a-zA-Z_][a-zA-Z0-9_]*?)\s+as\s*\(", flags=re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class SQLValidationResult:
    is_valid: bool
    sanitized_sql: str
    reasons: list[str]
    detected_tables: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "sanitized_sql": self.sanitized_sql,
            "reasons": self.reasons,
            "detected_tables": self.detected_tables,
        }


def _default_db_path() -> Path:
    return Path(load_settings().sqlite_db_path)


def _list_tables(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
              AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
    return {row[0].lower() for row in rows}


def _sanitize_sql(sql: str) -> str:
    cleaned = sql.strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()
    return cleaned


def _extract_cte_names(sql: str) -> set[str]:
    """Return lower-cased CTE names defined in a WITH clause."""
    return {match.group(1).lower() for match in CTE_NAME_PATTERN.finditer(sql)}


def _has_limit_clause(sql: str) -> bool:
    return bool(re.search(r"\blimit\s+\d+\b", sql, flags=re.IGNORECASE))


def validate_sql(sql: str, db_path: Path | None = None, *, max_limit: int | None = None) -> SQLValidationResult:
    path = db_path or _default_db_path()
    reasons: list[str] = []
    sanitized_sql = _sanitize_sql(sql)
    table_names = _list_tables(path)
    detected_tables = [name.lower() for name in TABLE_TOKEN_PATTERN.findall(sanitized_sql)]
    cte_names = _extract_cte_names(sanitized_sql)

    if not sanitized_sql:
        reasons.append("SQL is empty.")

    if ";" in sanitized_sql:
        reasons.append("Multiple statements are not allowed.")

    if not READ_QUERY_PATTERN.search(sanitized_sql):
        reasons.append("Only SELECT/CTE read-only queries are allowed.")

    for pattern in FORBIDDEN_SQL_PATTERNS:
        if re.search(pattern, sanitized_sql, flags=re.IGNORECASE):
            keyword = pattern.replace("\\b", "")
            reasons.append(f"Forbidden SQL keyword detected: {keyword}")

    unknown_tables = sorted({tbl for tbl in detected_tables if tbl not in table_names and tbl not in cte_names})
    if unknown_tables:
        reasons.append(f"Unknown table(s): {', '.join(unknown_tables)}")

    if max_limit is not None and max_limit > 0 and READ_QUERY_PATTERN.search(sanitized_sql):
        if not _has_limit_clause(sanitized_sql):
            sanitized_sql = f"{sanitized_sql}\nLIMIT {max_limit}"

    is_valid = len(reasons) == 0
    logger.info(
        "SQL validation finished (valid={is_valid}, reasons={reason_count}, detected_tables={tables})",
        is_valid=is_valid,
        reason_count=len(reasons),
        tables=detected_tables,
    )
    return SQLValidationResult(
        is_valid=is_valid,
        sanitized_sql=sanitized_sql,
        reasons=reasons,
        detected_tables=detected_tables,
    )
