from __future__ import annotations

from typing import Any

from app.config import load_settings
from app.graph.state import AgentState, TaskState
from app.llm import LLMClient
from app.logger import logger
from app.prompts import prompt_manager
from app.tools.visualization import (
    get_visualization_service,
    is_visualization_available,
)


def generate_visualization(state: AgentState) -> AgentState:
    """Generate chart visualization from SQL query results using E2B sandbox."""
    query = state.get("user_query", "")
    sql_result = state.get("sql_result", {})
    rows = sql_result.get("rows", [])

    # Check prerequisites
    if not rows:
        logger.warning("No data to visualize")
        return {
            "visualization": {
                "success": False,
                "error": "No data available for visualization",
            },
            "step_count": state.get("step_count", 0) + 1,
            "tool_history": [
                {
                    "tool": "generate_visualization",
                    "status": "skipped",
                    "reason": "no_data",
                }
            ],
        }

    if not is_visualization_available():
        logger.warning("Visualization not available - E2B not configured")
        return {
            "visualization": {
                "success": False,
                "error": "Visualization service not available (E2B not configured)",
            },
            "step_count": state.get("step_count", 0) + 1,
            "tool_history": [
                {
                    "tool": "generate_visualization",
                    "status": "skipped",
                    "reason": "e2b_not_configured",
                }
            ],
        }

    try:
        # Generate Python code via LLM
        python_code = _generate_visualization_code(query, rows)

        # Execute visualization
        service = get_visualization_service()
        result = service.generate_visualization(
            data_rows=rows,
            user_query=query,
            python_code=python_code,
        )

        # Build visualization state
        viz_state = {
            "success": result.success,
            "image_data": result.image_data,
            "image_format": result.image_format,
            "error": result.error,
            "code_executed": result.code_executed,
            "execution_time_ms": result.execution_time_ms,
        }

        return {
            "visualization": viz_state,
            "tool_history": [
                {
                    "tool": "generate_visualization",
                    "status": "ok" if result.success else "failed",
                    "has_image": result.image_data is not None,
                    "image_size": len(result.image_data) if result.image_data else 0,
                    "error": result.error,
                    "execution_time_ms": result.execution_time_ms,
                }
            ],
            "step_count": state.get("step_count", 0) + 1,
        }

    except Exception as exc:
        logger.exception("Visualization generation failed")
        return {
            "visualization": {"success": False, "error": str(exc)},
            "errors": [{"category": "VISUALIZATION_ERROR", "message": str(exc)}],
            "tool_history": [
                {
                    "tool": "generate_visualization",
                    "status": "failed",
                    "error": str(exc),
                }
            ],
            "step_count": state.get("step_count", 0) + 1,
        }


def _generate_visualization_code(query: str, data_sample: list[dict]) -> str | None:
    """Generate Python visualization code using LLM."""
    if not data_sample:
        return None

    # Build schema description
    columns = list(data_sample[0].keys())
    schema_desc = f"Columns: {', '.join(columns)}\n"
    schema_desc += f"Sample data (first {min(3, len(data_sample))} rows):\n"
    for i, row in enumerate(data_sample[:3]):
        schema_desc += f"  Row {i + 1}: {row}\n"

    # Detect chart type preference from query
    chart_type = _detect_chart_type(query)

    try:
        client = LLMClient.from_env()
        settings = load_settings()
        messages = prompt_manager.visualization_messages(
            query=query,
            schema_desc=schema_desc,
            chart_type=chart_type,
        )
        response = client.chat_completion(
            messages=messages,
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
            logger.info("Generated visualization code via LLM")
            return code
        else:
            logger.warning("LLM code missing plt.show(), falling back to template")
            return None

    except Exception as exc:
        logger.warning(
            "LLM visualization code generation failed: {error}", error=str(exc)
        )
        return None


def _detect_chart_type(query: str) -> str:
    """Detect chart type preference from query."""
    query_lower = query.lower()

    if any(
        word in query_lower
        for word in ["pie", "proportion", "percentage", "distribution"]
    ):
        return "pie"
    elif any(
        word in query_lower for word in ["line", "trend", "over time", "time series"]
    ):
        return "line"
    elif any(
        word in query_lower
        for word in ["scatter", "correlation", "relationship", "vs", "versus"]
    ):
        return "scatter"
    elif any(
        word in query_lower for word in ["histogram", "distribution", "frequency"]
    ):
        return "histogram"
    elif any(word in query_lower for word in ["bar", "compare", "ranking", "top"]):
        return "bar"
    else:
        return "auto"


def visualization_worker(task_state: TaskState) -> dict[str, Any]:
    """Worker node for visualization tasks in parallel execution."""
    query = task_state.get("query", "")
    sql_result = task_state.get("sql_result", {})
    rows = sql_result.get("rows", [])

    if not rows:
        return {
            **task_state,
            "status": "failed",
            "error": "No data to visualize",
        }

    if not is_visualization_available():
        return {
            **task_state,
            "status": "failed",
            "error": "E2B not configured",
        }

    try:
        service = get_visualization_service()
        result = service.generate_visualization(
            data_rows=rows,
            user_query=query,
        )

        return {
            **task_state,
            "status": "success" if result.success else "failed",
            "visualization_result": {
                "success": result.success,
                "image_data": result.image_data,
                "image_format": result.image_format,
                "error": result.error,
            },
            "execution_time_ms": result.execution_time_ms,
        }
    except Exception as exc:
        return {
            **task_state,
            "status": "failed",
            "error": str(exc),
        }
