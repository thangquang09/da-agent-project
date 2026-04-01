from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExecutionAccuracyResult:
    execution_match: bool
    pred_result: list[dict[str, Any]] | None
    gold_result: list[dict[str, Any]] | None
    result_comparison: str
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_match": self.execution_match,
            "pred_result": self.pred_result,
            "gold_result": self.gold_result,
            "result_comparison": self.result_comparison,
            "error": self.error,
        }


def _normalize_result_rows(rows: list[dict[str, Any]], limit: int = 100) -> list[tuple]:
    """Normalize result rows for comparison.

    Lowercases column names so that ``SELECT Name`` and ``SELECT name``
    are treated as equivalent.  Values are stringified for safe comparison
    across heterogeneous SQLite types.
    """
    compact = rows[:limit]
    normalized: list[tuple] = []
    for row in compact:
        items = tuple(sorted((str(k).lower(), str(v)) for k, v in row.items()))
        normalized.append(items)
    normalized.sort()
    return normalized


def _execute_sql(
    sql: str, db_path: Path
) -> tuple[list[dict[str, Any]] | None, str | None]:
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows, None
    except Exception as e:
        return None, str(e)


class ExecutionAccuracyEvaluator:
    def evaluate(
        self, pred_sql: str, gold_sql: str, db_path: str | Path | None
    ) -> ExecutionAccuracyResult:
        if not db_path:
            return ExecutionAccuracyResult(
                execution_match=False,
                pred_result=None,
                gold_result=None,
                result_comparison="no_db_path",
                error="No database path provided",
            )
        db_path = Path(db_path)
        if not db_path.exists():
            return ExecutionAccuracyResult(
                execution_match=False,
                pred_result=None,
                gold_result=None,
                result_comparison="db_not_found",
                error=f"Database not found: {db_path}",
            )
        pred_sql = pred_sql.strip() if pred_sql else ""
        gold_sql = gold_sql.strip() if gold_sql else ""
        if not pred_sql and not gold_sql:
            return ExecutionAccuracyResult(
                execution_match=True,
                pred_result=[],
                gold_result=[],
                result_comparison="match",
                error=None,
            )
        if not pred_sql:
            return ExecutionAccuracyResult(
                execution_match=False,
                pred_result=[],
                gold_result=None,
                result_comparison="no_pred_sql",
                error="No predicted SQL provided",
            )
        if not gold_sql:
            return ExecutionAccuracyResult(
                execution_match=False,
                pred_result=None,
                gold_result=[],
                result_comparison="no_gold_sql",
                error="No gold SQL provided",
            )
        gold_result, gold_error = _execute_sql(gold_sql, db_path)
        if gold_error:
            return ExecutionAccuracyResult(
                execution_match=False,
                pred_result=None,
                gold_result=None,
                result_comparison="gold_execution_error",
                error=f"Gold SQL execution error: {gold_error}",
            )
        pred_result, pred_error = _execute_sql(pred_sql, db_path)
        if pred_error:
            return ExecutionAccuracyResult(
                execution_match=False,
                pred_result=None,
                gold_result=gold_result,
                result_comparison="pred_execution_error",
                error=f"Pred SQL execution error: {pred_error}",
            )
        gold_rows = gold_result or []
        pred_rows = pred_result or []
        if len(gold_rows) == 0 and len(pred_rows) == 0:
            return ExecutionAccuracyResult(
                execution_match=True,
                pred_result=pred_rows,
                gold_result=gold_rows,
                result_comparison="match",
                error=None,
            )
        if len(gold_rows) != len(pred_rows):
            return ExecutionAccuracyResult(
                execution_match=False,
                pred_result=pred_rows,
                gold_result=gold_rows,
                result_comparison="row_count_mismatch",
                error=None,
            )
        gold_cols = {k.lower() for k in gold_rows[0].keys()} if gold_rows else set()
        pred_cols = {k.lower() for k in pred_rows[0].keys()} if pred_rows else set()
        if gold_cols != pred_cols:
            return ExecutionAccuracyResult(
                execution_match=False,
                pred_result=pred_rows,
                gold_result=gold_rows,
                result_comparison="column_mismatch",
                error=None,
            )
        normalized_gold = _normalize_result_rows(gold_rows)
        normalized_pred = _normalize_result_rows(pred_rows)
        if normalized_gold == normalized_pred:
            return ExecutionAccuracyResult(
                execution_match=True,
                pred_result=pred_rows,
                gold_result=gold_rows,
                result_comparison="match",
                error=None,
            )
        return ExecutionAccuracyResult(
            execution_match=False,
            pred_result=pred_rows,
            gold_result=gold_rows,
            result_comparison="data_mismatch",
            error=None,
        )
