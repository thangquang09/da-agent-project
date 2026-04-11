from __future__ import annotations

import base64
import csv
import io
import json
import os
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import load_settings
from app.logger import logger

# Load .env early so E2B_API_KEY is available
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# Conditional import - E2B is optional
try:
    from e2b_code_interpreter import Sandbox
    from e2b_code_interpreter.exceptions import TimeoutException as SandboxException

    E2B_AVAILABLE = True
except ImportError:
    E2B_AVAILABLE = False
    Sandbox = Any  # type: ignore[misc,assignment]
    SandboxException = RuntimeError  # type: ignore[misc,assignment]
    logger.warning(
        "E2B not installed. Visualization features disabled. Install with: pip install e2b-code-interpreter"
    )


@dataclass(frozen=True)
class VisualizationResult:
    """Result from visualization generation."""

    success: bool
    image_data: bytes | None = None
    image_format: str = "png"
    error: str | None = None
    code_executed: str = ""
    execution_time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "has_image": self.image_data is not None,
            "image_size": len(self.image_data) if self.image_data else 0,
            "image_format": self.image_format,
            "error": self.error,
            "code_lines": len(self.code_executed.splitlines()),
            "execution_time_ms": self.execution_time_ms,
        }


@dataclass(frozen=True)
class ReportAnalysisResult:
    """Result from deterministic grounded analysis inside a sandbox."""

    success: bool
    computed_stats: dict[str, Any] | None = None
    chart_manifest: dict[str, Any] | None = None
    chart_html: str | None = None
    image_data: bytes | None = None
    image_format: str = "png"
    error: str | None = None
    code_executed: str = ""
    execution_time_ms: float = 0.0


@dataclass(frozen=True)
class ContainerExecutionResult:
    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


class E2BVisualizationService:
    """Service for generating visualizations using E2B sandbox."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("E2B_API_KEY")
        self._sandbox: Any | None = None

    def close(self) -> None:
        """Close the E2B sandbox and cleanup resources."""
        if self._sandbox is not None:
            try:
                logger.info("Closing E2B sandbox")
                self._sandbox.close()
            except Exception as exc:
                logger.warning(f"Error closing E2B sandbox: {exc}")
            finally:
                self._sandbox = None

    def __enter__(self) -> E2BVisualizationService:
        """Context manager entry."""
        return self

    def __exit__(self, _exc_type: Any, _exc_val: Any, _exc_tb: Any) -> None:
        """Context manager exit - ensures sandbox cleanup."""
        self.close()

    def _get_sandbox(self, max_retries: int = 2, timeout_seconds: int = 300) -> Any:
        """Get or create E2B sandbox instance with retry logic.

        Args:
            max_retries: Maximum number of retry attempts for sandbox creation.
            timeout_seconds: Timeout in seconds for sandbox lifetime (max 3600).

        Returns:
            E2B Sandbox instance.

        Raises:
            RuntimeError: If sandbox creation fails after all retries.
        """
        if not E2B_AVAILABLE:
            raise RuntimeError(
                "E2B library not installed. Install with: pip install e2b-code-interpreter"
            )

        if not self.api_key:
            raise RuntimeError("E2B_API_KEY not configured in environment")

        if self._sandbox is not None:
            return self._sandbox

        # E2B SDK expects seconds, max 3600 (1 hour)
        timeout = min(timeout_seconds, 3600)

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                logger.info(
                    f"Creating E2B sandbox instance (attempt {attempt + 1}/{max_retries + 1})"
                )
                self._sandbox = Sandbox.create(
                    api_key=self.api_key,
                    timeout=timeout,
                )
                logger.info("E2B sandbox created successfully")
                return self._sandbox
            except SandboxException as exc:
                last_error = exc
                error_msg = str(exc).lower()

                # Check for specific error types
                if "sandbox was not found" in error_msg or "timeout" in error_msg:
                    logger.warning(
                        f"E2B sandbox creation timeout (attempt {attempt + 1}): {exc}"
                    )
                elif "api key" in error_msg or "unauthorized" in error_msg:
                    logger.error(f"E2B API key invalid: {exc}")
                    raise RuntimeError(
                        "E2B_API_KEY is invalid or unauthorized"
                    ) from exc
                else:
                    logger.warning(
                        f"E2B sandbox creation failed (attempt {attempt + 1}): {exc}"
                    )

                if attempt < max_retries:
                    wait_time = 2**attempt  # Exponential backoff: 1s, 2s
                    logger.info(f"Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
            except Exception as exc:
                last_error = exc
                logger.exception(
                    f"Unexpected error creating E2B sandbox (attempt {attempt + 1})"
                )
                if attempt < max_retries:
                    wait_time = 2**attempt
                    logger.info(f"Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)

        # All retries exhausted
        raise RuntimeError(
            f"Failed to create E2B sandbox after {max_retries + 1} attempts. "
            f"Last error: {last_error}. "
            "Please check your E2B_API_KEY and network connection."
        ) from last_error

    def _upload_data(
        self, data_rows: list[dict[str, Any]], filename: str = "data.csv"
    ) -> str:
        """Upload data as CSV to sandbox."""
        if not data_rows:
            raise ValueError("No data rows to visualize")

        # Convert to CSV
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=data_rows[0].keys())
        writer.writeheader()
        writer.writerows(data_rows)

        csv_content = output.getvalue()
        csv_bytes = csv_content.encode("utf-8")

        # Upload to sandbox
        path = f"/home/user/{filename}"
        sbx = self._get_sandbox()
        try:
            sbx.files.write(path, csv_bytes)
        except SandboxException as exc:
            if not self._sandbox_is_stale(exc):
                raise
            logger.warning("E2B sandbox became stale during upload, recreating sandbox")
            self._reset_sandbox()
            sbx = self._get_sandbox()
            sbx.files.write(path, csv_bytes)
        logger.info(
            f"Uploaded {len(data_rows)} rows to {path} ({len(csv_bytes)} bytes)"
        )

        return path

    def _sandbox_is_stale(self, exc: Exception) -> bool:
        error_msg = str(exc).lower()
        return "sandbox was not found" in error_msg or "timeout" in error_msg

    def _reset_sandbox(self) -> None:
        self.close()

    def _extract_image(self, execution: Any) -> tuple[bytes | None, str]:
        """Extract PNG image from execution results."""
        for result in execution.results:
            png_data = getattr(result, "png", None)
            if not png_data and hasattr(result, "_repr_png_"):
                png_data = result._repr_png_()
            if png_data:
                return base64.b64decode(png_data), "png"

            jpeg_data = getattr(result, "jpeg", None)
            if not jpeg_data and hasattr(result, "_repr_jpeg_"):
                jpeg_data = result._repr_jpeg_()
            if jpeg_data:
                return base64.b64decode(jpeg_data), "jpeg"
        return None, ""

    def _extract_json_result(
        self, execution: Any, marker: str
    ) -> dict[str, Any] | None:
        """Extract a JSON result emitted via display(JSON(...)) or stdout."""
        for result in execution.results:
            payload = None
            if hasattr(result, "_repr_json_"):
                payload = result._repr_json_()
            elif hasattr(result, "json"):
                payload = result.json
            if isinstance(payload, dict) and payload.get(marker):
                return payload

        logs = getattr(execution, "logs", None)
        stdout_lines = getattr(logs, "stdout", []) if logs is not None else []
        for line in stdout_lines:
            try:
                payload = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and payload.get(marker):
                return payload
        return None

    def _extract_html_result(self, execution: Any, marker: str) -> str | None:
        """Extract HTML emitted via display(HTML(...))."""
        for result in execution.results:
            html = None
            if hasattr(result, "_repr_html_"):
                html = result._repr_html_()
            elif hasattr(result, "html"):
                html = result.html
            if isinstance(html, str) and marker in html:
                return html
        return None

    def generate_visualization(
        self,
        data_rows: list[dict[str, Any]],
        user_query: str,
        chart_type: str = "auto",
        python_code: str | None = None,
    ) -> VisualizationResult:
        """
        Generate chart using E2B sandbox.

        Args:
            data_rows: SQL query results as list of dicts
            user_query: Original user question
            chart_type: 'auto', 'bar', 'line', 'scatter', 'histogram', 'pie'
            python_code: Optional pre-generated Python code (if None, will use template)

        Returns:
            VisualizationResult with image data or error
        """
        start_time = time.monotonic()

        if not E2B_AVAILABLE:
            return VisualizationResult(
                success=False,
                error="E2B library not installed. Run: pip install e2b-code-interpreter",
            )

        if not self.api_key:
            return VisualizationResult(
                success=False,
                error="E2B_API_KEY not configured in environment",
            )

        try:
            # Upload data
            data_path = self._upload_data(data_rows, "query_data.csv")

            # Generate or use provided Python code
            if python_code:
                code_to_run = python_code
            else:
                code_to_run = self._generate_chart_code(
                    user_query=user_query,
                    data_path=data_path,
                    chart_type=chart_type,
                    data_sample=data_rows[:5] if data_rows else [],
                )

            # Execute in sandbox
            logger.info("Executing visualization code in E2B sandbox")
            sbx = self._get_sandbox()
            execution = sbx.run_code(code_to_run)

            # Check for errors
            if execution.error:
                logger.error(f"E2B execution error: {execution.error}")
                return VisualizationResult(
                    success=False,
                    error=f"{execution.error.name}: {execution.error.value}",
                    code_executed=code_to_run,
                    execution_time_ms=(time.monotonic() - start_time) * 1000,
                )

            # Extract image
            image_data, image_format = self._extract_image(execution)

            if not image_data:
                return VisualizationResult(
                    success=False,
                    error="No chart generated. Code must use plt.show() or save figure.",
                    code_executed=code_to_run,
                    execution_time_ms=(time.monotonic() - start_time) * 1000,
                )

            execution_time_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                f"Visualization generated successfully ({len(image_data)} bytes, {execution_time_ms:.0f}ms)"
            )

            return VisualizationResult(
                success=True,
                image_data=image_data,
                image_format=image_format,
                code_executed=code_to_run,
                execution_time_ms=execution_time_ms,
            )

        except SandboxException as exc:
            error_msg = str(exc)
            logger.error(f"E2B sandbox error: {error_msg}")

            # Provide user-friendly error messages
            if (
                "sandbox was not found" in error_msg.lower()
                or "timeout" in error_msg.lower()
            ):
                user_error = (
                    "E2B sandbox timed out while starting. "
                    "This may be due to high demand. Please try again later."
                )
            elif "api key" in error_msg.lower() or "unauthorized" in error_msg.lower():
                user_error = (
                    "E2B API key is invalid or expired. Please check your E2B_API_KEY."
                )
            else:
                user_error = f"E2B sandbox error: {error_msg}"

            return VisualizationResult(
                success=False,
                error=user_error,
                code_executed=python_code if python_code else "",
                execution_time_ms=(time.monotonic() - start_time) * 1000,
            )
        except Exception as exc:
            logger.exception("Visualization generation failed")
            return VisualizationResult(
                success=False,
                error=str(exc),
                code_executed=python_code if python_code else "",
                execution_time_ms=(time.monotonic() - start_time) * 1000,
            )

    def generate_grounded_report_analysis(
        self,
        data_rows: list[dict[str, Any]],
        user_query: str,
        section_title: str,
    ) -> ReportAnalysisResult:
        """Generate deterministic stats + chart artifacts for report sections."""
        start_time = time.monotonic()

        if not E2B_AVAILABLE:
            return ReportAnalysisResult(
                success=False,
                error="E2B library not installed. Run: pip install e2b-code-interpreter",
            )

        if not self.api_key:
            return ReportAnalysisResult(
                success=False,
                error="E2B_API_KEY not configured in environment",
            )

        if not data_rows:
            return ReportAnalysisResult(
                success=False,
                error="No data rows available for report analysis",
            )

        try:
            data_path = self._upload_data(data_rows, "report_section_data.csv")
            column_types = self._infer_column_types_from_rows(data_rows)
            code_to_run = self._generate_report_analysis_code(
                data_path=data_path,
                user_query=user_query,
                section_title=section_title,
                column_types=column_types,
            )

            logger.info("Executing grounded report analysis in E2B sandbox")
            sbx = self._get_sandbox()
            execution = sbx.run_code(code_to_run)

            if execution.error:
                return ReportAnalysisResult(
                    success=False,
                    error=f"{execution.error.name}: {execution.error.value}",
                    code_executed=code_to_run,
                    execution_time_ms=(time.monotonic() - start_time) * 1000,
                )

            image_data, image_format = self._extract_image(execution)
            json_payload = self._extract_json_result(execution, "__report_analysis__")
            html_payload = self._extract_html_result(
                execution, 'data-report-analysis="true"'
            )

            if not json_payload:
                return ReportAnalysisResult(
                    success=False,
                    error="Sandbox did not return computed stats for the report section.",
                    code_executed=code_to_run,
                    execution_time_ms=(time.monotonic() - start_time) * 1000,
                )

            execution_time_ms = (time.monotonic() - start_time) * 1000
            return ReportAnalysisResult(
                success=True,
                computed_stats=json_payload.get("computed_stats"),
                chart_manifest=json_payload.get("chart_manifest"),
                chart_html=html_payload,
                image_data=image_data,
                image_format=image_format or "png",
                code_executed=code_to_run,
                execution_time_ms=execution_time_ms,
            )
        except SandboxException as exc:
            return ReportAnalysisResult(
                success=False,
                error=str(exc),
                execution_time_ms=(time.monotonic() - start_time) * 1000,
            )
        except Exception as exc:
            logger.exception("Grounded report analysis failed")
            return ReportAnalysisResult(
                success=False,
                error=str(exc),
                execution_time_ms=(time.monotonic() - start_time) * 1000,
            )

    def _generate_chart_code(
        self,
        user_query: str,
        data_path: str,
        chart_type: str,
        data__sample: list[dict],
    ) -> str:
        """Generate Python code for visualization based on chart type."""

        # Build column info from sample
        columns_info = ""
        if data_sample:
            columns = list(data_sample[0].keys())
            columns_info = f"# Available columns: {', '.join(columns)}\n"

        # Chart type specific templates
        templates = {
            "bar": self._bar_chart_template,
            "line": self._line_chart_template,
            "scatter": self._scatter_chart_template,
            "histogram": self._histogram_template,
            "pie": self._pie_chart_template,
            "auto": self._auto_chart_template,
        }

        template_fn = templates.get(chart_type, templates["auto"])
        return template_fn(data_path, user_query, columns_info, data_sample)

    @staticmethod
    def _infer_column_types_from_rows(
        data_rows: list[dict[str, Any]],
    ) -> dict[str, str]:
        """Infer column types from Python values in the first non-null row.

        Returns a mapping of column_name → "integer"|"float"|"datetime"|"text".
        This is used to seed pd.read_csv(dtype=...) in the sandbox so that
        integer columns are never mis-detected as datetimes.
        """
        if not data_rows:
            return {}
        col_types: dict[str, str] = {}
        for row in data_rows[:20]:  # sample up to 20 rows for robustness
            for col, val in row.items():
                if col in col_types:
                    continue
                if val is None or val == "":
                    continue
                if isinstance(val, bool):
                    col_types[col] = "text"
                elif isinstance(val, int):
                    col_types[col] = "integer"
                elif isinstance(val, float):
                    col_types[col] = "float"
                else:
                    # String — check if it looks like a date
                    s = str(val).strip()
                    if (
                        len(s) >= 8
                        and ("-" in s or "/" in s)
                        and any(c.isdigit() for c in s)
                    ):
                        col_types[col] = "datetime"
                    else:
                        col_types[col] = "text"
        return col_types

    def _generate_report_analysis_code(
        self,
        data_path: str,
        user_query: str,
        section_title: str,
        column_types: dict[str, str] | None = None,
    ) -> str:
        """Return deterministic Python code for report-only grounded analysis."""
        query_json = json.dumps(user_query, ensure_ascii=False)
        title_json = json.dumps(section_title, ensure_ascii=False)
        data_path_json = json.dumps(data_path)
        column_types_json = json.dumps(column_types or {})
        return f'''import base64
import io
import json
import math

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from IPython.display import HTML, JSON, display

QUERY = {query_json}
SECTION_TITLE = {title_json}
DATA_PATH = {data_path_json}
COLUMN_TYPES = {column_types_json}

sns.set_style("whitegrid")

# Build dtype mapping from known types (integer/float) so pandas
# never mis-parses numeric columns as datetime objects.
_dtype_map = {{}}
_parse_dates = []
for _col, _ctype in COLUMN_TYPES.items():
    if _ctype == "integer":
        _dtype_map[_col] = "Int64"   # nullable integer — handles missing values
    elif _ctype == "float":
        _dtype_map[_col] = "float64"
    elif _ctype == "datetime":
        _parse_dates.append(_col)
    else:
        _dtype_map[_col] = "object"

df = pd.read_csv(DATA_PATH, dtype=_dtype_map if _dtype_map else None, parse_dates=_parse_dates if _parse_dates else False)

# Convert Int64 (nullable) to regular int64 where fully non-null to simplify downstream ops
for _col in df.columns:
    if pd.api.types.is_integer_dtype(df[_col]):
        df[_col] = df[_col].astype("int64", errors="ignore")


def normalize_number(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return int(value)
        return round(float(value), 6)
    if isinstance(value, (int, str, bool)):
        return value
    try:
        numeric = float(value)
        if math.isfinite(numeric) and numeric.is_integer():
            return int(numeric)
        return round(numeric, 6)
    except Exception:
        return str(value)


def display_number(value):
    normalized = normalize_number(value)
    if normalized is None:
        return "null"
    if isinstance(normalized, float):
        text = f"{{normalized:.6f}}".rstrip("0").rstrip(".")
        return text if text else "0"
    return str(normalized)


def metric_entry(value, label=None):
    entry = {{
        "value": normalize_number(value),
        "display_value": display_number(value),
    }}
    if label:
        entry["label"] = label
    return entry


def normalized_row_entry(row, columns):
    return {{
        col: normalize_number(row[col])
        for col in columns
    }}


def detect_datetime_column(frame, known_types=None):
    """Find a datetime column.

    If *known_types* is provided (from COLUMN_TYPES hint), only columns whose
    type is explicitly marked as "datetime" are considered — integer/float
    columns are never probed with pd.to_datetime, preventing false positives.
    When no hint is available we fall back to the previous heuristic but skip
    numeric columns.
    """
    if known_types:
        # Use authoritative type hint: only look at columns marked as datetime
        for col in frame.columns:
            if known_types.get(col) == "datetime":
                series = pd.to_datetime(frame[col], errors="coerce")
                if series.notna().sum() >= max(2, len(frame) // 2):
                    return col, series
        return None, None
    # Fallback heuristic — skip numeric columns to avoid false positives
    for col in frame.columns:
        if pd.api.types.is_numeric_dtype(frame[col]):
            continue
        series = pd.to_datetime(frame[col], errors="coerce")
        if series.notna().sum() >= max(2, len(frame) // 2):
            return col, series
    return None, None


numeric_cols = [
    col for col in df.columns if pd.api.types.is_numeric_dtype(df[col])
]
datetime_col, datetime_series = detect_datetime_column(df, known_types=COLUMN_TYPES)
category_cols = [col for col in df.columns if col not in numeric_cols]

stats = {{
    "section_title": SECTION_TITLE,
    "query": QUERY,
    "row_count": int(len(df)),
    "metrics": {{}},
    "series": [],
    "grouped_rows": [],
    "row_bindings": {{
        "group_columns": category_cols,
        "metric_columns": numeric_cols,
    }},
    "rankings": {{}},
    "comparisons": {{}},
    "data_quality": {{
        "warnings": [],
        "columns": list(df.columns),
        "numeric_columns": numeric_cols,
    }},
}}

manifest = {{
    "chart_type": "table",
    "x_field": None,
    "y_field": None,
    "row_count_used": int(len(df)),
    "notes": [],
}}

plt.figure(figsize=(12, 6))

if df.empty:
    stats["data_quality"]["warnings"].append("No rows returned for this section.")
    plt.text(0.5, 0.5, "No data available", ha="center", va="center", fontsize=16)
    plt.axis("off")
elif len(df) == 1 and numeric_cols:
    manifest["chart_type"] = "bar"
    manifest["x_field"] = "metric"
    manifest["y_field"] = "value"
    one_row = df.iloc[0]
    metric_rows = []
    for col in numeric_cols:
        stats["metrics"][col] = metric_entry(one_row[col], label=col)
        metric_rows.append({{"metric": col, "value": float(one_row[col])}})
    metric_df = pd.DataFrame(metric_rows)
    stats["series"] = [
        {{"x": row["metric"], "y": normalize_number(row["value"]), "display_y": display_number(row["value"])}}
        for _, row in metric_df.iterrows()
    ]
    sns.barplot(data=metric_df, x="metric", y="value", palette="crest")
    plt.xticks(rotation=30, ha="right")
elif datetime_col and numeric_cols:
    y_col = numeric_cols[0]
    frame = df.copy()
    frame["_dt_x"] = datetime_series
    frame = frame.dropna(subset=["_dt_x"]).sort_values("_dt_x")
    manifest["chart_type"] = "line"
    manifest["x_field"] = datetime_col
    manifest["y_field"] = y_col
    if frame.empty:
        stats["data_quality"]["warnings"].append("Datetime parsing removed all rows.")
        plt.text(0.5, 0.5, "No valid time-series rows", ha="center", va="center", fontsize=16)
        plt.axis("off")
    else:
        series_points = []
        for _, row in frame.iterrows():
            y_val = normalize_number(row[y_col])
            series_points.append({{
                "x": row["_dt_x"].strftime("%Y-%m-%d"),
                "y": y_val,
                "display_y": display_number(row[y_col]),
            }})
        stats["series"] = series_points
        stats["metrics"]["first_value"] = metric_entry(frame.iloc[0][y_col], label=y_col)
        stats["metrics"]["last_value"] = metric_entry(frame.iloc[-1][y_col], label=y_col)
        stats["metrics"]["max_value"] = metric_entry(frame[y_col].max(), label=y_col)
        stats["metrics"]["min_value"] = metric_entry(frame[y_col].min(), label=y_col)
        first_val = float(frame.iloc[0][y_col])
        last_val = float(frame.iloc[-1][y_col])
        stats["comparisons"]["delta_from_first_to_last"] = metric_entry(last_val - first_val)
        if first_val != 0:
            stats["comparisons"]["pct_change_from_first_to_last"] = metric_entry(((last_val - first_val) / first_val) * 100)
        sns.lineplot(data=frame, x="_dt_x", y=y_col, marker="o")
        plt.xticks(rotation=30, ha="right")
else:
    y_col = numeric_cols[0] if numeric_cols else None
    x_col = None
    for col in category_cols:
        if col != datetime_col:
            x_col = col
            break

    if category_cols and numeric_cols:
        stats["grouped_rows"] = [
            normalized_row_entry(row, df.columns)
            for _, row in df.head(50).iterrows()
        ]

    if x_col and y_col:
        manifest["chart_type"] = "bar"
        manifest["x_field"] = x_col
        manifest["y_field"] = y_col
        ranked = df[[x_col, y_col]].dropna().copy()
        ranked[y_col] = pd.to_numeric(ranked[y_col], errors="coerce")
        ranked = ranked.dropna(subset=[y_col]).sort_values(y_col, ascending=False)
        if ranked.empty:
            stats["data_quality"]["warnings"].append("No valid category-value pairs for charting.")
            plt.text(0.5, 0.5, "No valid category-value rows", ha="center", va="center", fontsize=16)
            plt.axis("off")
        else:
            chart_df = ranked.head(20)
            stats["series"] = [
                {{
                    "x": str(row[x_col]),
                    "y": normalize_number(row[y_col]),
                    "display_y": display_number(row[y_col]),
                }}
                for _, row in chart_df.iterrows()
            ]
            stats["rankings"]["top_items"] = [
                {{
                    "label": str(row[x_col]),
                    "value": normalize_number(row[y_col]),
                    "display_value": display_number(row[y_col]),
                }}
                for _, row in ranked.head(5).iterrows()
            ]
            stats["rankings"]["bottom_items"] = [
                {{
                    "label": str(row[x_col]),
                    "value": normalize_number(row[y_col]),
                    "display_value": display_number(row[y_col]),
                }}
                for _, row in ranked.tail(5).sort_values(y_col, ascending=True).iterrows()
            ]
            stats["metrics"]["max_value"] = metric_entry(ranked[y_col].max(), label=y_col)
            stats["metrics"]["min_value"] = metric_entry(ranked[y_col].min(), label=y_col)
            stats["metrics"]["total_value"] = metric_entry(ranked[y_col].sum(), label=y_col)
            sns.barplot(data=chart_df, x=x_col, y=y_col, palette="viridis")
            plt.xticks(rotation=30, ha="right")
    elif y_col:
        manifest["chart_type"] = "histogram"
        manifest["x_field"] = y_col
        manifest["y_field"] = "count"
        numeric_series = pd.to_numeric(df[y_col], errors="coerce").dropna()
        if numeric_series.empty:
            stats["data_quality"]["warnings"].append("No numeric values available for histogram.")
            plt.text(0.5, 0.5, "No numeric data", ha="center", va="center", fontsize=16)
            plt.axis("off")
        else:
            stats["metrics"]["mean"] = metric_entry(numeric_series.mean(), label=y_col)
            stats["metrics"]["median"] = metric_entry(numeric_series.median(), label=y_col)
            stats["metrics"]["max"] = metric_entry(numeric_series.max(), label=y_col)
            stats["metrics"]["min"] = metric_entry(numeric_series.min(), label=y_col)
            sns.histplot(numeric_series, bins=min(20, max(5, len(numeric_series) // 2)), kde=False)
    else:
        stats["data_quality"]["warnings"].append("No numeric columns available for grounded analysis.")
        manifest["notes"].append("Rendered a placeholder because the section has no numeric fields.")
        plt.text(0.5, 0.5, "No numeric columns available", ha="center", va="center", fontsize=16)
        plt.axis("off")

for col in numeric_cols:
    series = pd.to_numeric(df[col], errors="coerce").dropna()
    if not series.empty and col not in stats["metrics"]:
        stats["metrics"][col] = {{
            "min": metric_entry(series.min(), label=col),
            "max": metric_entry(series.max(), label=col),
            "avg": metric_entry(series.mean(), label=col),
            "count": metric_entry(series.count(), label=col),
        }}

plt.title(SECTION_TITLE or QUERY)
plt.tight_layout()

html_rows = []
for key, value in stats["metrics"].items():
    if isinstance(value, dict) and "display_value" in value:
        html_rows.append(f"<tr><td>{{key}}</td><td>{{value['display_value']}}</td></tr>")

if not html_rows:
    html_rows.append("<tr><td colspan='2'>No computed metrics available.</td></tr>")

html = (
    '<div data-report-analysis="true">'
    f"<h3>{{SECTION_TITLE}}</h3>"
    f"<p>{{QUERY}}</p>"
    "<table border='1' cellpadding='6' cellspacing='0'>"
    "<thead><tr><th>Metric</th><th>Value</th></tr></thead>"
    f"<tbody>{{''.join(html_rows)}}</tbody>"
    "</table>"
    "</div>"
)

payload = {{
    "__report_analysis__": True,
    "computed_stats": stats,
    "chart_manifest": manifest,
}}

buffer = io.BytesIO()
plt.gcf().savefig(buffer, format="png", bbox_inches="tight")

display(JSON(payload))
display(HTML(html))
print("__REPORT_ANALYSIS_JSON__:" + json.dumps(stats, ensure_ascii=False))
print("__REPORT_CHART_MANIFEST__:" + json.dumps(manifest, ensure_ascii=False))
print("__REPORT_HTML__:" + html.replace("\\n", " "))
print("__CHART_PNG_BASE64__:" + base64.b64encode(buffer.getvalue()).decode("utf-8"))
plt.show()
'''

    def _bar_chart_template(
        self, data_path: str, query: str, columns_info: str, _sample: list
    ) -> str:
        return f'''import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

# Load data
df = pd.read_csv("{data_path}")
{columns_info}
# Create figure
plt.figure(figsize=(12, 6))
sns.set_style("whitegrid")

# Auto-detect columns for bar chart
if len(df.columns) >= 2:
    # Assume first column is category, second is value
    x_col = df.columns[0]
    y_col = df.columns[1]
    
    # Limit to top 20 categories if too many
    if df[x_col].nunique() > 20:
        top_categories = df.groupby(x_col)[y_col].sum().nlargest(20).index
        df = df[df[x_col].isin(top_categories)]
    
    sns.barplot(data=df, x=x_col, y=y_col, palette="viridis")
    plt.title("{query}", fontsize=14, pad=20)
    plt.xlabel(x_col, fontsize=12)
    plt.ylabel(y_col, fontsize=12)
    plt.xticks(rotation=45, ha='right')
else:
    df.iloc[:, 0].value_counts().plot(kind='bar')
    plt.title("{query}")
    plt.xticks(rotation=45)

plt.tight_layout()
plt.show()
'''

    def _line_chart_template(
        self, data_path: str, query: str, columns_info: str, _sample: list
    ) -> str:
        return f'''import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

# Load data
df = pd.read_csv("{data_path}")
{columns_info}
# Create figure
plt.figure(figsize=(12, 6))
sns.set_style("whitegrid")

# Auto-detect columns for line chart
if len(df.columns) >= 2:
    # Look for date/time column
    date_cols = [col for col in df.columns if any(keyword in col.lower() 
                 for keyword in ['date', 'time', 'day', 'month', 'year'])]
    
    if date_cols:
        x_col = date_cols[0]
        y_col = [col for col in df.columns if col != x_col][0]
        
        # Try to parse as datetime
        try:
            df[x_col] = pd.to_datetime(df[x_col])
            df = df.sort_values(x_col)
        except:
            pass
    else:
        x_col = df.columns[0]
        y_col = df.columns[1]
    
    sns.lineplot(data=df, x=x_col, y=y_col, marker='o', linewidth=2.5)
    plt.title("{query}", fontsize=14, pad=20)
    plt.xlabel(x_col, fontsize=12)
    plt.ylabel(y_col, fontsize=12)
    plt.xticks(rotation=45)
else:
    df.iloc[:, 0].plot(kind='line')
    plt.title("{query}")

plt.tight_layout()
plt.show()
'''

    def _scatter_chart_template(
        self, data_path: str, query: str, columns_info: str, _sample: list
    ) -> str:
        return f'''import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

# Load data
df = pd.read_csv("{data_path}")
{columns_info}
# Create figure
plt.figure(figsize=(10, 8))
sns.set_style("whitegrid")

# Use first two numeric columns
numeric_cols = df.select_dtypes(include=['float64', 'int64']).columns.tolist()
if len(numeric_cols) >= 2:
    x_col, y_col = numeric_cols[0], numeric_cols[1]
    
    # If there's a third column, use it for color
    if len(numeric_cols) >= 3:
        hue_col = numeric_cols[2]
        sns.scatterplot(data=df, x=x_col, y=y_col, hue=hue_col, palette="viridis", s=100, alpha=0.7)
        plt.legend(title=hue_col, bbox_to_anchor=(1.05, 1), loc='upper left')
    else:
        sns.scatterplot(data=df, x=x_col, y=y_col, s=100, alpha=0.7, color='steelblue')
    
    plt.title("{query}", fontsize=14, pad=20)
    plt.xlabel(x_col, fontsize=12)
    plt.ylabel(y_col, fontsize=12)
else:
    plt.text(0.5, 0.5, "Insufficient numeric data for scatter plot", 
             ha='center', va='center', transform=plt.gca().transAxes)

plt.tight_layout()
plt.show()
'''

    def _histogram_template(
        self, data_path: str, query: str, columns_info: str, _sample: list
    ) -> str:
        return f'''import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

# Load data
df = pd.read_csv("{data_path}")
{columns_info}
# Create figure
plt.figure(figsize=(12, 6))
sns.set_style("whitegrid")

# Use first numeric column
numeric_cols = df.select_dtypes(include=['float64', 'int64']).columns.tolist()
if numeric_cols:
    col = numeric_cols[0]
    sns.histplot(data=df, x=col, kde=True, color='steelblue', bins=30)
    plt.title("{query}", fontsize=14, pad=20)
    plt.xlabel(col, fontsize=12)
    plt.ylabel("Frequency", fontsize=12)
else:
    plt.text(0.5, 0.5, "No numeric data for histogram", 
             ha='center', va='center', transform=plt.gca().transAxes)

plt.tight_layout()
plt.show()
'''

    def _pie_chart_template(
        self, data_path: str, query: str, columns_info: str, _sample: list
    ) -> str:
        return f'''import pandas as pd
import matplotlib.pyplot as plt

# Load data
df = pd.read_csv("{data_path}")
{columns_info}
# Create figure
plt.figure(figsize=(10, 8))

# Use first categorical column and first numeric column
categorical_cols = df.select_dtypes(include=['object']).columns.tolist()
numeric_cols = df.select_dtypes(include=['float64', 'int64']).columns.tolist()

if categorical_cols and numeric_cols:
    cat_col = categorical_cols[0]
    num_col = numeric_cols[0]
    
    # Aggregate by category
    agg_data = df.groupby(cat_col)[num_col].sum().sort_values(ascending=False)
    
    # Limit to top 8 categories
    if len(agg_data) > 8:
        other_sum = agg_data.iloc[8:].sum()
        agg_data = agg_data.iloc[:8]
        agg_data['Others'] = other_sum
    
    colors = plt.cm.Set3(range(len(agg_data)))
    plt.pie(agg_data.values, labels=agg_data.index, autopct='%1.1f%%', 
            colors=colors, startangle=90)
    plt.title("{query}", fontsize=14, pad=20)
else:
    plt.text(0.5, 0.5, "Insufficient data for pie chart", 
             ha='center', va='center', transform=plt.gca().transAxes)

plt.axis('equal')
plt.tight_layout()
plt.show()
'''

    def _auto_chart_template(
        self, data_path: str, query: str, columns_info: str, _sample: list
    ) -> str:
        """Auto-detect best chart type based on data."""
        return f'''import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

# Load data
df = pd.read_csv("{data_path}")
{columns_info}
# Analyze data to choose best chart type
numeric_cols = df.select_dtypes(include=['float64', 'int64']).columns.tolist()
categorical_cols = df.select_dtypes(include=['object']).columns.tolist()
row_count = len(df)

plt.figure(figsize=(12, 6))
sns.set_style("whitegrid")

# Decision logic for chart type
if row_count <= 20 and len(categorical_cols) > 0 and len(numeric_cols) > 0:
    # Small dataset with categories - use bar chart
    cat_col = categorical_cols[0]
    num_col = numeric_cols[0]
    
    if df[cat_col].nunique() <= 20:
        sns.barplot(data=df, x=cat_col, y=num_col, palette="viridis")
        plt.xticks(rotation=45, ha='right')
    else:
        # Too many categories - show top 15
        top_data = df.nlargest(15, num_col)
        sns.barplot(data=top_data, x=cat_col, y=num_col, palette="viridis")
        plt.xticks(rotation=45, ha='right')
    
    plt.title("{query}", fontsize=14, pad=20)
    plt.xlabel(cat_col, fontsize=12)
    plt.ylabel(num_col, fontsize=12)

elif any(keyword in str(col).lower() for col in df.columns for keyword in ['date', 'time']) and len(numeric_cols) > 0:
    # Time series data - use line chart
    date_cols = [col for col in df.columns if any(keyword in col.lower() 
                 for keyword in ['date', 'time', 'day', 'month', 'year'])]
    x_col = date_cols[0] if date_cols else df.columns[0]
    y_col = numeric_cols[0]
    
    try:
        df[x_col] = pd.to_datetime(df[x_col])
        df = df.sort_values(x_col)
    except:
        pass
    
    sns.lineplot(data=df, x=x_col, y=y_col, marker='o', linewidth=2.5)
    plt.title("{query}", fontsize=14, pad=20)
    plt.xlabel(x_col, fontsize=12)
    plt.ylabel(y_col, fontsize=12)
    plt.xticks(rotation=45)

elif len(numeric_cols) >= 2:
    # Multiple numeric columns - use scatter or line
    x_col, y_col = numeric_cols[0], numeric_cols[1]
    sns.scatterplot(data=df, x=x_col, y=y_col, s=100, alpha=0.7, color='steelblue')
    plt.title("{query}", fontsize=14, pad=20)
    plt.xlabel(x_col, fontsize=12)
    plt.ylabel(y_col, fontsize=12)

else:
    # Default - use bar chart of first column
    df.iloc[:, 0].value_counts().plot(kind='bar', color='steelblue')
    plt.title("{query}", fontsize=14, pad=20)
    plt.xticks(rotation=45)

plt.tight_layout()
plt.show()
'''


class DockerVisualizationService(E2BVisualizationService):
    """Service for generating visualizations using a local Docker container."""

    def __init__(
        self,
        image: str | None = None,
        bootstrap_command: str | None = None,
        timeout_seconds: int | None = None,
        workdir: str | None = None,
    ):
        settings = load_settings()
        self.image = image or settings.docker_sandbox_image
        self.base_image = settings.docker_sandbox_base_image
        self.bootstrap_command = (
            bootstrap_command
            if bootstrap_command is not None
            else settings.docker_sandbox_bootstrap_command
        )
        self.timeout_seconds = (
            timeout_seconds or settings.docker_sandbox_timeout_seconds
        )
        self.workdir = workdir or settings.docker_sandbox_workdir
        self.api_key = None
        self._sandbox = None
        self._image_ready = False
        self._image_lock = threading.Lock()

    def close(self) -> None:
        """Docker runs are ephemeral; nothing persistent to close."""

    def _docker_available(self) -> bool:
        return shutil.which("docker") is not None

    def _run_container(
        self,
        *,
        files: dict[str, bytes],
        command: str,
        timeout_seconds: int | None = None,
    ) -> ContainerExecutionResult:
        if not self._docker_available():
            return ContainerExecutionResult(
                success=False,
                stderr="Docker CLI is not installed or not available in PATH.",
                exit_code=127,
            )

        image_error = self._ensure_image_ready(timeout_seconds=timeout_seconds)
        if image_error is not None:
            return ContainerExecutionResult(
                success=False,
                stderr=image_error,
                exit_code=1,
            )

        timeout = timeout_seconds or self.timeout_seconds
        with tempfile.TemporaryDirectory(prefix="viz-sandbox-") as tmpdir:
            tmp_path = Path(tmpdir)
            tmp_path.chmod(
                stat.S_IRUSR
                | stat.S_IWUSR
                | stat.S_IXUSR
                | stat.S_IRGRP
                | stat.S_IWGRP
                | stat.S_IXGRP
                | stat.S_IROTH
                | stat.S_IWOTH
                | stat.S_IXOTH
            )
            for relative_path, content in files.items():
                host_path = tmp_path / relative_path
                host_path.parent.mkdir(parents=True, exist_ok=True)
                host_path.write_bytes(content)

            docker_cmd = [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--cpus",
                "1",
                "--memory",
                "1g",
                "--pids-limit",
                "256",
                "--security-opt",
                "no-new-privileges",
                "--cap-drop",
                "ALL",
                "-v",
                f"{tmp_path}:{self.workdir}",
                "-w",
                self.workdir,
                self.image,
                "sh",
                "-lc",
                command,
            ]

            try:
                completed = subprocess.run(
                    docker_cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                return ContainerExecutionResult(
                    success=False,
                    stdout=exc.stdout or "",
                    stderr=(exc.stderr or "") + "\nDocker sandbox timed out.",
                    exit_code=124,
                )
            except Exception as exc:  # noqa: BLE001
                return ContainerExecutionResult(
                    success=False,
                    stderr=str(exc),
                    exit_code=1,
                )

            return ContainerExecutionResult(
                success=completed.returncode == 0,
                stdout=completed.stdout,
                stderr=completed.stderr,
                exit_code=completed.returncode,
            )

    def _ensure_image_ready(self, timeout_seconds: int | None = None) -> str | None:
        if self._image_ready:
            return None

        with self._image_lock:
            if self._image_ready:
                return None

            inspect = subprocess.run(
                ["docker", "image", "inspect", self.image],
                capture_output=True,
                text=True,
                timeout=timeout_seconds or self.timeout_seconds,
                check=False,
            )
            if inspect.returncode == 0:
                self._image_ready = True
                return None

            if not self.bootstrap_command.strip():
                return (
                    f"Docker sandbox image '{self.image}' is not available and "
                    "DOCKER_SANDBOX_BOOTSTRAP_COMMAND is empty."
                )

            logger.info(
                "Building Docker sandbox image {image} from base {base}",
                image=self.image,
                base=self.base_image,
            )
            with tempfile.TemporaryDirectory(prefix="viz-sandbox-build-") as tmpdir:
                dockerfile = Path(tmpdir) / "Dockerfile"
                dockerfile.write_text(
                    "\n".join(
                        [
                            f"FROM {self.base_image}",
                            "ENV PYTHONDONTWRITEBYTECODE=1",
                            "ENV PYTHONUNBUFFERED=1",
                            f"RUN {self.bootstrap_command}",
                            f"WORKDIR {self.workdir}",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                build = subprocess.run(
                    [
                        "docker",
                        "build",
                        "-t",
                        self.image,
                        tmpdir,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=max(timeout_seconds or self.timeout_seconds, 600),
                    check=False,
                )
            if build.returncode != 0:
                return (
                    f"Failed to build Docker sandbox image '{self.image}'. "
                    f"{(build.stderr or build.stdout).strip()}"
                )

            self._image_ready = True
            return None

    def generate_visualization(
        self,
        data_rows: list[dict[str, Any]],
        user_query: str,
        chart_type: str = "auto",
        python_code: str | None = None,
    ) -> VisualizationResult:
        start_time = time.monotonic()

        if not data_rows:
            return VisualizationResult(
                success=False,
                error="No data rows to visualize",
            )

        data_path = "query_data.csv"
        code_to_run = python_code or self._generate_chart_code(
            user_query=user_query,
            data_path=str(Path(self.workdir) / data_path),
            chart_type=chart_type,
            data_sample=data_rows[:5] if data_rows else [],
        )
        wrapped_code = self._wrap_visualization_code(code_to_run)
        output_path = Path("outputs/chart.png")
        command = self._compose_container_command("sandbox_entry.py")
        files = {
            data_path: self._rows_to_csv_bytes(data_rows),
            "sandbox_entry.py": wrapped_code.encode("utf-8"),
        }
        execution = self._run_container(files=files, command=command)
        execution_time_ms = (time.monotonic() - start_time) * 1000

        if not execution.success:
            error_msg = self._format_docker_error(execution)
            logger.warning("Docker visualization failed: {error}", error=error_msg)
            return VisualizationResult(
                success=False,
                error=error_msg,
                code_executed=code_to_run,
                execution_time_ms=execution_time_ms,
            )

        image_data = self._extract_marked_binary(
            execution.stdout, "__CHART_PNG_BASE64__"
        )
        if not image_data:
            return VisualizationResult(
                success=False,
                error="No chart generated. Code must create a Matplotlib figure.",
                code_executed=code_to_run,
                execution_time_ms=execution_time_ms,
            )

        return VisualizationResult(
            success=True,
            image_data=image_data,
            image_format="png",
            code_executed=code_to_run,
            execution_time_ms=execution_time_ms,
        )

    def generate_grounded_report_analysis(
        self,
        data_rows: list[dict[str, Any]],
        user_query: str,
        section_title: str,
    ) -> ReportAnalysisResult:
        start_time = time.monotonic()

        if not data_rows:
            return ReportAnalysisResult(
                success=False,
                error="No data rows available for report analysis",
            )

        data_path = "report_section_data.csv"
        column_types = self._infer_column_types_from_rows(data_rows)
        code_to_run = self._generate_report_analysis_code(
            data_path=str(Path(self.workdir) / data_path),
            user_query=user_query,
            section_title=section_title,
            column_types=column_types,
        )
        command = self._compose_container_command("report_analysis.py")
        files = {
            data_path: self._rows_to_csv_bytes(data_rows),
            "report_analysis.py": code_to_run.encode("utf-8"),
        }
        execution = self._run_container(files=files, command=command)
        execution_time_ms = (time.monotonic() - start_time) * 1000

        if not execution.success:
            return ReportAnalysisResult(
                success=False,
                error=self._format_docker_error(execution),
                code_executed=code_to_run,
                execution_time_ms=execution_time_ms,
            )

        computed_stats = self._extract_marked_json(
            execution.stdout, "__REPORT_ANALYSIS_JSON__"
        )
        chart_manifest = self._extract_marked_json(
            execution.stdout, "__REPORT_CHART_MANIFEST__"
        )
        chart_html = self._extract_marked_text(execution.stdout, "__REPORT_HTML__")
        image_data = self._extract_marked_binary(
            execution.stdout, "__CHART_PNG_BASE64__"
        )

        if not computed_stats:
            return ReportAnalysisResult(
                success=False,
                error="Sandbox did not return computed stats for the report section.",
                code_executed=code_to_run,
                execution_time_ms=execution_time_ms,
            )

        return ReportAnalysisResult(
            success=True,
            computed_stats=computed_stats,
            chart_manifest=chart_manifest,
            chart_html=chart_html,
            image_data=image_data,
            image_format="png",
            code_executed=code_to_run,
            execution_time_ms=execution_time_ms,
        )

    def _compose_container_command(self, script_name: str) -> str:
        return f"python {script_name}"

    def _rows_to_csv_bytes(self, data_rows: list[dict[str, Any]]) -> bytes:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=data_rows[0].keys())
        writer.writeheader()
        writer.writerows(data_rows)
        return output.getvalue().encode("utf-8")

    def _format_docker_error(self, execution: ContainerExecutionResult) -> str:
        stderr = execution.stderr.strip()
        stdout = execution.stdout.strip()
        details = stderr or stdout or "Unknown Docker sandbox failure."
        return f"Docker sandbox failed (exit_code={execution.exit_code}): {details}"

    def _extract_marked_json(
        self,
        stdout: str,
        marker: str,
    ) -> dict[str, Any] | None:
        text = self._extract_marked_text(stdout, marker)
        if not text:
            return None
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _extract_marked_binary(self, stdout: str, marker: str) -> bytes | None:
        text = self._extract_marked_text(stdout, marker)
        if not text:
            return None
        try:
            return base64.b64decode(text)
        except Exception:  # noqa: BLE001
            return None

    def _extract_marked_text(self, stdout: str, marker: str) -> str | None:
        prefix = f"{marker}:"
        for line in stdout.splitlines():
            if line.startswith(prefix):
                return line[len(prefix) :].strip()
        return None

    def _wrap_visualization_code(self, python_code: str) -> str:
        return f"""import base64
import io
import traceback

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _codex_show(*args, **kwargs):
    if plt.get_fignums():
        buffer = io.BytesIO()
        plt.gcf().savefig(buffer, format="png", bbox_inches="tight")
        print("__CHART_PNG_BASE64__:" + base64.b64encode(buffer.getvalue()).decode("utf-8"))


plt.show = _codex_show

try:
{self._indent_code(python_code, 4)}
    if plt.get_fignums():
        _codex_show()
except Exception:
    traceback.print_exc()
    raise
"""

    def _indent_code(self, python_code: str, spaces: int) -> str:
        prefix = " " * spaces
        return "\n".join(
            prefix + line if line.strip() else line for line in python_code.splitlines()
        )


class NullVisualizationService:
    """Disabled sandbox implementation."""

    def generate_visualization(
        self,
        data_rows: list[dict[str, Any]],
        user_query: str,
        chart_type: str = "auto",
        python_code: str | None = None,
    ) -> VisualizationResult:
        return VisualizationResult(
            success=False,
            error="Visualization sandbox is disabled. Configure TYPE_OF_SANDBOX=docker or TYPE_OF_SANDBOX=e2b.",
            code_executed=python_code or "",
        )

    def generate_grounded_report_analysis(
        self,
        data_rows: list[dict[str, Any]],
        user_query: str,
        section_title: str,
    ) -> ReportAnalysisResult:
        return ReportAnalysisResult(
            success=False,
            error="Report sandbox is disabled. Configure TYPE_OF_SANDBOX=docker or TYPE_OF_SANDBOX=e2b.",
        )

    def close(self) -> None:
        return None


# Singleton instance
_visualization_service: (
    E2BVisualizationService
    | DockerVisualizationService
    | NullVisualizationService
    | None
) = None
_visualization_service_key: str | None = None


def get_visualization_service() -> (
    E2BVisualizationService | DockerVisualizationService | NullVisualizationService
):
    """Get or create the visualization service singleton."""
    global _visualization_service, _visualization_service_key
    settings = load_settings()
    sandbox_type = settings.type_of_sandbox
    if _visualization_service is None or _visualization_service_key != sandbox_type:
        if _visualization_service is not None:
            try:
                _visualization_service.close()
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to close previous visualization service instance"
                )
        if sandbox_type == "docker":
            _visualization_service = DockerVisualizationService()
        elif sandbox_type == "e2b":
            _visualization_service = E2BVisualizationService()
        else:
            _visualization_service = NullVisualizationService()
        _visualization_service_key = sandbox_type
    return _visualization_service


def is_visualization_available() -> bool:
    """Check if visualization features are available for the configured sandbox."""
    settings = load_settings()
    sandbox_type = settings.type_of_sandbox
    if sandbox_type == "docker":
        return shutil.which("docker") is not None
    if sandbox_type == "e2b":
        if not E2B_AVAILABLE:
            return False
        api_key = os.getenv("E2B_API_KEY")
        return bool(api_key)
    return False
