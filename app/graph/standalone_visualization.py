from __future__ import annotations

import base64
import csv
import io
from typing import Any

from app.graph.state import TaskState
from app.llm import LLMClient
from app.logger import logger
from app.tools.visualization import (
    get_visualization_service,
    is_visualization_available,
)


def standalone_visualization_worker(task_state: TaskState) -> dict[str, Any]:
    """Worker for standalone visualization tasks with user-provided raw data.

    This handles cases where users provide data directly in their query,
    e.g., "vẽ biểu đồ với các giá trị 10, 20, 30"
    """
    query = task_state.get("query", "")
    raw_data = task_state.get("raw_data", [])

    if not raw_data:
        return {
            "visualization": {
                "success": False,
                "error": "No raw data provided for visualization",
            },
            "status": "failed",
        }

    if not is_visualization_available():
        return {
            "visualization": {
                "success": False,
                "error": "Visualization service not available (E2B not configured)",
            },
            "status": "skipped",
        }

    try:
        # Step 1: Generate Python visualization code using LLM
        python_code = _generate_standalone_visualization_code(query, raw_data)

        if not python_code:
            return {
                "visualization": {
                    "success": False,
                    "error": "Failed to generate visualization code",
                },
                "status": "failed",
            }

        # Step 2: Upload raw data as CSV to E2B sandbox
        csv_content = _convert_to_csv(raw_data)
        service = get_visualization_service()
        sbx = service._get_sandbox()
        data_path = "/home/user/query_data.csv"
        sbx.files.write(data_path, csv_content.encode("utf-8"))

        # Step 3: Execute visualization code
        execution = sbx.run_code(python_code)

        if execution.error:
            logger.error(f"Standalone visualization execution error: {execution.error}")
            return {
                "visualization": {
                    "success": False,
                    "error": f"{execution.error.name}: {execution.error.value}",
                    "code_executed": python_code,
                },
                "status": "failed",
            }

        # Step 4: Extract image
        image_data, image_format = _extract_image(execution)

        if not image_data:
            return {
                "visualization": {
                    "success": False,
                    "error": "No chart generated. Code must use plt.show()",
                    "code_executed": python_code,
                },
                "status": "failed",
            }

        return {
            "visualization": {
                "success": True,
                "image_data": image_data,
                "image_format": image_format,
                "code_executed": python_code,
                "execution_time_ms": 0.0,
            },
            "status": "success",
        }

    except Exception as exc:
        logger.exception("Standalone visualization failed")
        error_msg = str(exc)

        # Provide user-friendly error messages for common issues
        if "sandbox" in error_msg.lower() and (
            "timeout" in error_msg.lower() or "not found" in error_msg.lower()
        ):
            user_error = (
                "Visualization sandbox timed out while starting. "
                "This may be due to high demand. Please try again later."
            )
        elif "api key" in error_msg.lower():
            user_error = (
                "Visualization service API key is invalid. Please contact support."
            )
        else:
            user_error = f"Visualization failed: {error_msg}"

        return {
            "visualization": {
                "success": False,
                "error": user_error,
            },
            "status": "failed",
        }


def _generate_standalone_visualization_code(
    query: str, raw_data: list[dict[str, Any]]
) -> str | None:
    """Generate Python visualization code for standalone data using LLM."""
    if not raw_data:
        return None

    # Build schema description
    columns = list(raw_data[0].keys())
    schema_desc = f"Columns: {', '.join(columns)}\n"
    schema_desc += f"Data ({len(raw_data)} rows):\n"
    for i, row in enumerate(raw_data[:5]):
        schema_desc += f"  Row {i + 1}: {row}\n"

    system_prompt = """You are a Python data visualization expert. Write code using pandas, seaborn, and matplotlib.

CRITICAL REQUIREMENTS:
1. Read data from '/home/user/query_data.csv' using pandas
2. Choose the EXACT chart type the user requested (bar chart, line chart, scatter plot, pie chart, histogram)
3. Use seaborn for the visualization (sns.barplot, sns.lineplot, sns.scatterplot, etc.)
4. Make the chart visually appealing with proper styling
5. Set appropriate figure size (12x6 or similar)
6. Add title, labels, and rotate x-axis labels if needed
7. END your code with plt.show() to display the chart
8. Do NOT include any explanations, markdown, or comments - only the Python code
9. The code must be self-contained and runnable

Available libraries: pandas, seaborn, matplotlib, numpy

IMPORTANT: If the user explicitly mentions a chart type (e.g., "bar chart", "line chart"), use that exact type. Do not default to scatter plot."""

    user_prompt = f"""Create visualization for this data based on the user's request.

User Query: {query}

Data Schema:
{schema_desc}

Write Python code that:
1. Reads the CSV file from '/home/user/query_data.csv'
2. Creates the appropriate chart type as requested by the user
3. Makes it visually appealing
4. Ends with plt.show()

Return ONLY the Python code, no markdown or explanations."""

    try:
        from app.config import load_settings

        settings = load_settings()
        client = LLMClient.from_env()

        response = client.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=settings.model_synthesis,
            temperature=0.2,
        )

        code = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

        # Clean up code (remove markdown fences if present)
        import re

        code = re.sub(r"^```python\s*", "", code)
        code = re.sub(r"^```\s*", "", code)
        code = re.sub(r"```$", "", code)
        code = code.strip()

        if code and "plt.show()" in code:
            logger.info(
                "Generated standalone visualization code via LLM for query: {query}",
                query=query[:50],
            )
            return code
        else:
            logger.warning("LLM code missing plt.show() for standalone visualization")
            return None

    except Exception as exc:
        logger.warning(
            "LLM standalone visualization code generation failed: {error}",
            error=str(exc),
        )
        return None


def _convert_to_csv(raw_data: list[dict[str, Any]]) -> str:
    """Convert raw data to CSV format."""
    if not raw_data:
        return ""

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=raw_data[0].keys())
    writer.writeheader()
    writer.writerows(raw_data)
    return output.getvalue()


def _extract_image(execution: Any) -> tuple[bytes | None, str]:
    """Extract PNG image from execution results."""
    for result in execution.results:
        if result.png:
            return base64.b64decode(result.png), "png"
        if result.jpeg:
            return base64.b64decode(result.jpeg), "jpeg"
    return None, ""
