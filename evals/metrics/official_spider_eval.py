from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Path to the vendored test-suite-sql-eval repo (relative to project root)
_VENDOR_DIR = Path(__file__).resolve().parents[2] / "vendor" / "test-suite-sql-eval"
_EVAL_SCRIPT = _VENDOR_DIR / "evaluation.py"

HARDNESS_LEVELS = ("easy", "medium", "hard", "extra", "all")


@dataclass
class HardnessScore:
    count: int
    exec_accuracy: float


@dataclass
class OfficialSpiderResult:
    """Result returned by the official test-suite-sql-eval script."""

    # Overall execution accuracy across all hardness levels
    exec_accuracy_all: float

    # Per-hardness breakdown
    breakdown: dict[str, HardnessScore] = field(default_factory=dict)

    # Raw stdout from the subprocess (for debugging)
    raw_output: str = ""

    # Error message if the subprocess failed
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "exec_accuracy_all": self.exec_accuracy_all,
            "breakdown": {
                level: {"count": s.count, "exec_accuracy": s.exec_accuracy}
                for level, s in self.breakdown.items()
            },
            "error": self.error,
        }


def _parse_stdout(stdout: str) -> OfficialSpiderResult:
    """
    Parse the official evaluation script's stdout.

    The script prints lines like:
        easy                 medium               hard               extra              all
        count                0                    2                  0                  0
        =====================   EXECUTION ACCURACY     =====================
        execution            0.000                1.000              0.000              0.000

    We extract count and exec accuracy per hardness level.
    """
    lines = stdout.splitlines()

    # Find the EXECUTION ACCURACY block
    exec_block_idx = None
    for i, line in enumerate(lines):
        if "EXECUTION ACCURACY" in line.upper():
            exec_block_idx = i
            break

    if exec_block_idx is None:
        return OfficialSpiderResult(
            exec_accuracy_all=0.0,
            error=f"Could not find EXECUTION ACCURACY section in output:\n{stdout[:500]}",
            raw_output=stdout,
        )

    # The format is:
    #   <header: easy medium hard extra all>
    #   count <counts...>
    #   ===================== EXECUTION ACCURACY =====================
    #   execution <accuracies...>
    # So count line is BEFORE the separator, execution line is AFTER
    count_values: list[str] = []
    exec_values: list[str] = []

    # Look for count line before the separator
    for line in reversed(lines[:exec_block_idx]):
        stripped = line.strip()
        if re.match(r"^count\s+\d", stripped):
            count_values = stripped.split()[1:]  # skip "count" label
            break

    # Look for execution line after the separator
    for line in lines[exec_block_idx:]:
        stripped = line.strip()
        if re.match(r"^execution\s+[0-9.]", stripped):
            exec_values = stripped.split()[1:]  # skip "execution" label
            break

    if not exec_values:
        return OfficialSpiderResult(
            exec_accuracy_all=0.0,
            error=f"Could not parse execution accuracy values:\n{stdout[:800]}",
            raw_output=stdout,
        )

    # exec_values aligns with HARDNESS_LEVELS (easy medium hard extra all [joint_all])
    breakdown: dict[str, HardnessScore] = {}
    for i, level in enumerate(HARDNESS_LEVELS):
        if i < len(exec_values):
            count = int(count_values[i]) if i < len(count_values) else 0
            try:
                acc = float(exec_values[i])
            except ValueError:
                acc = 0.0
            breakdown[level] = HardnessScore(count=count, exec_accuracy=acc)

    exec_all = breakdown.get(
        "all", HardnessScore(count=0, exec_accuracy=0.0)
    ).exec_accuracy

    return OfficialSpiderResult(
        exec_accuracy_all=exec_all,
        breakdown=breakdown,
        raw_output=stdout,
        error=None,
    )


class OfficialSpiderEvaluator:
    """
    Adapter that runs the official `test-suite-sql-eval` script in a subprocess
    and returns structured results.

    Usage::

        evaluator = OfficialSpiderEvaluator(db_dir="data/spider_1/spider_data/database")
        result = evaluator.evaluate_batch(
            gold_pairs=[("SELECT ...", "db_id"), ...],
            pred_sqls=["SELECT ...", ...],
        )
        print(result.exec_accuracy_all)  # e.g. 0.712
    """

    def __init__(
        self,
        db_dir: str | Path,
        plug_value: bool = False,
        keep_distinct: bool = False,
        timeout: int = 600,
    ) -> None:
        # Always resolve to absolute path — subprocess runs with cwd=vendor dir
        self.db_dir = Path(db_dir).resolve()
        self.plug_value = plug_value
        self.keep_distinct = keep_distinct
        self.timeout = timeout

        if not _EVAL_SCRIPT.exists():
            raise FileNotFoundError(
                f"Official eval script not found at {_EVAL_SCRIPT}. "
                "Run: git clone --depth=1 https://github.com/taoyds/test-suite-sql-eval.git vendor/test-suite-sql-eval"
            )
        if not self.db_dir.exists():
            raise FileNotFoundError(f"Database directory not found: {self.db_dir}")

    def evaluate_batch(
        self,
        gold_pairs: list[tuple[str, str]],
        pred_sqls: list[str],
    ) -> OfficialSpiderResult:
        """
        Run the official Spider evaluation on a batch of predictions.

        Args:
            gold_pairs: List of (gold_sql, db_id) tuples — matches dev_gold.sql format.
            pred_sqls:  List of predicted SQL strings, same order as gold_pairs.

        Returns:
            OfficialSpiderResult with exec_accuracy_all and per-hardness breakdown.
        """
        if len(gold_pairs) != len(pred_sqls):
            return OfficialSpiderResult(
                exec_accuracy_all=0.0,
                error=f"Length mismatch: {len(gold_pairs)} gold vs {len(pred_sqls)} pred",
            )

        if not gold_pairs:
            return OfficialSpiderResult(
                exec_accuracy_all=0.0,
                error="Empty input — no cases to evaluate",
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            gold_file = tmp / "gold.sql"
            pred_file = tmp / "pred.sql"

            # Normalize SQLs to single-line format (official eval expects this)
            def _normalize_sql(sql: str) -> str:
                # Replace newlines and multiple spaces with single space
                return " ".join(sql.split())

            # Gold format: "<sql>\t<db_id>"
            gold_lines = [
                f"{_normalize_sql(sql)}\t{db_id}" for sql, db_id in gold_pairs
            ]
            gold_file.write_text("\n".join(gold_lines), encoding="utf-8")

            # Pred format: one SQL per line (same order)
            pred_lines = [_normalize_sql(sql) for sql in pred_sqls]
            pred_file.write_text("\n".join(pred_lines), encoding="utf-8")

            cmd = [
                "uv",
                "run",
                "python",
                "evaluation.py",  # relative to cwd
                "--gold",
                str(gold_file),
                "--pred",
                str(pred_file),
                "--db",
                str(self.db_dir),
                "--etype",
                "exec",
            ]
            if self.plug_value:
                cmd.append("--plug_value")
            if self.keep_distinct:
                cmd.append("--keep_distinct")

            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    cwd=str(_VENDOR_DIR),  # cwd = vendor dir so relative imports work
                )
            except subprocess.TimeoutExpired:
                return OfficialSpiderResult(
                    exec_accuracy_all=0.0,
                    error=f"Evaluation timed out after {self.timeout}s",
                )
            except Exception as exc:
                return OfficialSpiderResult(
                    exec_accuracy_all=0.0,
                    error=f"Subprocess error: {exc}",
                )

            stdout = proc.stdout or ""
            stderr = proc.stderr or ""

            if proc.returncode != 0:
                return OfficialSpiderResult(
                    exec_accuracy_all=0.0,
                    raw_output=stdout,
                    error=f"Eval script exited with code {proc.returncode}.\nSTDERR: {stderr[:500]}",
                )

            result = _parse_stdout(stdout)
            return result
