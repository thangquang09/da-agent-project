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
TABLE_TOKEN_PATTERN = re.compile(
    r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)\b", flags=re.IGNORECASE
)
# Pattern to match the first CTE after WITH (supports RECURSIVE)
CTE_NAME_PATTERN = re.compile(
    r"\bWITH\s+(?:RECURSIVE\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s*\(",
    flags=re.IGNORECASE | re.DOTALL,
)
# Pattern to match subsequent CTEs in a chain (after comma)
CTE_CHAIN_PATTERN = re.compile(
    r"\)\s*,\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s*\(", flags=re.IGNORECASE | re.DOTALL
)


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
    """Return lower-cased CTE names defined in a WITH clause.

    Handles:
    - Simple CTEs: WITH cte1 AS (...)
    - Recursive CTEs: WITH RECURSIVE cte1 AS (...)
    - Chained CTEs: WITH cte1 AS (...), cte2 AS (...), cte3 AS (...)
    """
    names = set()

    # Find initial CTE after WITH (handles RECURSIVE keyword)
    for match in CTE_NAME_PATTERN.finditer(sql):
        names.add(match.group(1).lower())

    # Find chained CTEs after commas
    for match in CTE_CHAIN_PATTERN.finditer(sql):
        names.add(match.group(1).lower())

    return names


def _has_limit_clause(sql: str) -> bool:
    return bool(re.search(r"\blimit\s+\d+\b", sql, flags=re.IGNORECASE))


# Pattern to match aggregate functions in SQL
AGGREGATE_PATTERN = re.compile(r"\b(COUNT|AVG|SUM|MIN|MAX)\s*\(", flags=re.IGNORECASE)

# Pattern to match GROUP BY clause
GROUP_BY_PATTERN = re.compile(r"\bGROUP\s+BY\b", flags=re.IGNORECASE)


def _is_aggregate_query(sql: str) -> bool:
    """Check if the query has aggregate functions in the final SELECT.

    For CTE queries, we look at the final SELECT (after the last closing paren
    that isn't part of a CTE definition).
    """
    # Find the final SELECT clause (after all CTEs)
    sql_upper = sql.upper()

    # For CTE queries, we need to find the final SELECT after all CTEs
    # CTEs end with a closing paren followed by a SELECT
    if sql_upper.strip().startswith("WITH"):
        # Find the position of the final SELECT that's not inside a CTE
        # Strategy: find all positions of SELECT and determine which is the final one
        # outside of CTE definitions
        depth = 0
        in_cte_definition = True
        final_select_start = -1

        i = 0
        while i < len(sql_upper):
            if sql_upper[i] == "(":
                depth += 1
            elif sql_upper[i] == ")":
                depth -= 1
                if depth == 0 and in_cte_definition:
                    # Look ahead for SELECT
                    remaining = sql_upper[i + 1 :].strip()
                    if remaining.startswith("SELECT"):
                        final_select_start = i + 1 + remaining.find("SELECT")
                        in_cte_definition = False
            elif (
                depth == 0
                and not in_cte_definition
                and sql_upper[i:].startswith("SELECT")
            ):
                final_select_start = i
                break
            i += 1

        # If we didn't find a final SELECT outside CTEs, search from the end
        if final_select_start == -1:
            # Look for the last SELECT that's not inside parentheses
            depth = 0
            for i in range(len(sql_upper) - 1, -1, -1):
                if sql_upper[i] == ")":
                    depth += 1
                elif sql_upper[i] == "(":
                    depth -= 1
                elif (
                    depth == 0
                    and i + 6 <= len(sql_upper)
                    and sql_upper[i : i + 6] == "SELECT"
                ):
                    final_select_start = i
                    break

        if final_select_start != -1:
            final_select_sql = sql[final_select_start:]
            return bool(AGGREGATE_PATTERN.search(final_select_sql))

    # For simple queries, check the whole query
    return bool(AGGREGATE_PATTERN.search(sql))


def _has_group_by(sql: str) -> bool:
    """Check if the query has a GROUP BY clause."""
    return bool(GROUP_BY_PATTERN.search(sql))


def validate_sql(
    sql: str, db_path: Path | None = None, *, max_limit: int | None = None
) -> SQLValidationResult:
    path = db_path or _default_db_path()
    reasons: list[str] = []
    sanitized_sql = _sanitize_sql(sql)
    table_names = _list_tables(path)
    detected_tables = [
        name.lower() for name in TABLE_TOKEN_PATTERN.findall(sanitized_sql)
    ]
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

    unknown_tables = sorted(
        {
            tbl
            for tbl in detected_tables
            if tbl not in table_names and tbl not in cte_names
        }
    )
    if unknown_tables:
        reasons.append(f"Unknown table(s): {', '.join(unknown_tables)}")

    if (
        max_limit is not None
        and max_limit > 0
        and READ_QUERY_PATTERN.search(sanitized_sql)
    ):
        if not _has_limit_clause(sanitized_sql):
            # Don't add LIMIT to aggregate queries or queries with GROUP BY
            # as this would truncate data before aggregation
            if not _is_aggregate_query(sanitized_sql) and not _has_group_by(
                sanitized_sql
            ):
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
