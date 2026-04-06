from __future__ import annotations

from typing import Any

from app.graph.state import TaskState
from app.llm import LLMClient
from app.logger import logger
from app.prompts import prompt_manager
from app.tools.visualization import (
    get_visualization_service,
    is_visualization_available,
)


def _normalize_raw_data(raw_data: list[Any]) -> list[dict[str, Any]]:
    """Normalize raw numeric data to chart-ready format.

    Accepts a list of numbers (e.g., [10, 30, 60]) and converts to
    list of dicts with Category/Value keys for visualization.

    Also accepts pre-formatted list[dict] (passthrough).
    """
    if not raw_data:
        return []

    # Already formatted
    if isinstance(raw_data[0], dict):
        return raw_data  # type: ignore[return-value]

    result: list[dict[str, Any]] = []
    for idx, val in enumerate(raw_data, start=1):
        try:
            result.append(
                {"Category": f"Category {idx}", "Value": float(val)}
            )
        except (ValueError, TypeError):
            continue
    return result


def inline_data_worker(task_state: TaskState) -> dict[str, Any]:
    """InlineDataWorker — handles visualization for user-provided data.
    
    This worker:
    - Accepts raw data directly from the query (inline_data source)
    - NEVER generates SQL
    - NEVER calls validate_sql()
    - NEVER touches the database
    - Returns WorkerArtifact with artifact_type="chart"
    
    Data source: task_state.get("raw_data") — list of dicts with "value" keys
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
            # WorkerArtifact fields
            "artifact_type": "chart",
            "artifact_status": "failed",
            "artifact_payload": {"error": "No raw data provided"},
            "artifact_evidence": {"source": "input_validation"},
            "artifact_terminal": False,
            "artifact_recommended_action": "clarify",
        }

    if not is_visualization_available():
        return {
            "visualization": {
                "success": False,
                "error": "Visualization service not available (E2B not configured)",
            },
            "status": "skipped",
            # WorkerArtifact fields
            "artifact_type": "chart",
            "artifact_status": "failed",
            "artifact_payload": {"error": "Visualization service not available"},
            "artifact_evidence": {"source": "e2b_check"},
            "artifact_terminal": False,
            "artifact_recommended_action": "clarify",
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
                # WorkerArtifact fields
                "artifact_type": "chart",
                "artifact_status": "failed",
                "artifact_payload": {"error": "Failed to generate visualization code"},
                "artifact_evidence": {"source": "llm_code_generation"},
                "artifact_terminal": False,
                "artifact_recommended_action": "clarify",
            }

        # Step 2: Execute visualization in the configured sandbox
        normalized_rows = _normalize_raw_data(raw_data)
        service = get_visualization_service()
        result = service.generate_visualization(
            data_rows=normalized_rows,
            user_query=query,
            python_code=python_code,
        )

        if not result.success:
            logger.error(
                "Standalone visualization execution error: {error}",
                error=result.error,
            )
            return {
                "visualization": {
                    "success": False,
                    "error": result.error,
                    "code_executed": result.code_executed,
                },
                "status": "failed",
                # WorkerArtifact fields
                "artifact_type": "chart",
                "artifact_status": "failed",
                "artifact_payload": {"error": result.error},
                "artifact_evidence": {"source": "code_execution"},
                "artifact_terminal": False,
                "artifact_recommended_action": "clarify",
            }

        return {
            "visualization": {
                "success": True,
                "image_data": result.image_data,
                "image_format": result.image_format,
                "code_executed": result.code_executed,
                "execution_time_ms": result.execution_time_ms,
                "terminal": True,
                "recommended_next_action": "finalize",
            },
            "status": "success",
            # WorkerArtifact fields
            "artifact_type": "chart",
            "artifact_status": "success",
            "artifact_payload": {
                "image_data": result.image_data,
                "image_format": result.image_format,
                "chart_type": "unknown",  # Would need LLM to determine
                "normalized_rows": len(normalized_rows),
            },
            "artifact_evidence": {
                "source": "inline_data",
                "normalized_rows": len(normalized_rows),
            },
            "artifact_terminal": True,
            "artifact_recommended_action": "finalize",
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
            # WorkerArtifact fields
            "artifact_type": "chart",
            "artifact_status": "failed",
            "artifact_payload": {"error": user_error},
            "artifact_evidence": {"source": "exception_handler"},
            "artifact_terminal": False,
            "artifact_recommended_action": "clarify",
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

    try:
        from app.config import load_settings

        settings = load_settings()
        client = LLMClient.from_env()
        messages = prompt_manager.visualization_messages(
            query=query,
            schema_desc=schema_desc,
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

# Backward compatibility alias
standalone_visualization_worker = inline_data_worker
