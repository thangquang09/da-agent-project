from __future__ import annotations

import re


def needs_safety_limit(sql: str) -> bool:
    """Check if SQL needs a safety LIMIT appended.

    Returns False for queries that are already bounded:
    - Already has LIMIT
    - Uses aggregate functions (AVG, MAX, MIN, COUNT, SUM, etc.)
    - Has GROUP BY (bounded by distinct groups)
    - Uses window functions (RANK, ROW_NUMBER, etc.)
    - Uses SELECT DISTINCT (bounded by cardinality)

    Returns True for detail/raw data queries that could return thousands of rows.
    """
    sql_upper = sql.upper().strip()

    if re.search(r"\bLIMIT\b", sql_upper):
        return False

    if re.search(
        r"\b(AVG|MAX|MIN|COUNT|SUM|STDDEV|VARIANCE|MEDIAN|GROUP_CONCAT)\s*\(",
        sql_upper,
    ):
        return False

    if re.search(r"\bGROUP\s+BY\b", sql_upper):
        return False

    if re.search(
        r"\b(RANK|DENSE_RANK|ROW_NUMBER|NTILE|LAG|LEAD|FIRST_VALUE|LAST_VALUE|NTH_VALUE)\s*\(",
        sql_upper,
    ):
        return False

    if re.search(r"\bOVER\s*\(", sql_upper):
        return False

    if re.search(r"\bSELECT\s+DISTINCT\b", sql_upper):
        return False

    return True


def apply_safety_limit(sql: str, limit: int = 200) -> str:
    """Add LIMIT to detail queries only, never to aggregations."""
    if needs_safety_limit(sql):
        return f"{sql.rstrip(';').rstrip()}\nLIMIT {limit}"
    return sql
