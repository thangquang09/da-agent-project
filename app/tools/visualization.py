from __future__ import annotations

import base64
import csv
import io
import json
import os
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

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
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
        sbx = self._get_sandbox()
        path = f"/home/user/{filename}"
        sbx.files.write(path, csv_bytes)
        logger.info(
            f"Uploaded {len(data_rows)} rows to {path} ({len(csv_bytes)} bytes)"
        )

        return path

    def _extract_image(self, execution: Any) -> tuple[bytes | None, str]:
        """Extract PNG image from execution results."""
        for result in execution.results:
            if result.png:
                # Base64 decode
                return base64.b64decode(result.png), "png"
            if result.jpeg:
                return base64.b64decode(result.jpeg), "jpeg"
        return None, ""

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

    def _generate_chart_code(
        self,
        user_query: str,
        data_path: str,
        chart_type: str,
        data_sample: list[dict],
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

    def _bar_chart_template(
        self, data_path: str, query: str, columns_info: str, sample: list
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
        self, data_path: str, query: str, columns_info: str, sample: list
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
        self, data_path: str, query: str, columns_info: str, sample: list
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
        self, data_path: str, query: str, columns_info: str, sample: list
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
        self, data_path: str, query: str, columns_info: str, sample: list
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
        self, data_path: str, query: str, columns_info: str, sample: list
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


# Singleton instance
_visualization_service: E2BVisualizationService | None = None


def get_visualization_service() -> E2BVisualizationService:
    """Get or create the visualization service singleton."""
    global _visualization_service
    if _visualization_service is None:
        _visualization_service = E2BVisualizationService()
    return _visualization_service


def is_visualization_available() -> bool:
    """Check if visualization features are available (E2B configured)."""
    if not E2B_AVAILABLE:
        return False
    api_key = os.getenv("E2B_API_KEY")
    return bool(api_key)
