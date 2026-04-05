from __future__ import annotations

import base64
import csv
import io
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
                # WorkerArtifact fields
                "artifact_type": "chart",
                "artifact_status": "failed",
                "artifact_payload": {"error": f"{execution.error.name}: {execution.error.value}"},
                "artifact_evidence": {"source": "code_execution", "error_type": execution.error.name},
                "artifact_terminal": False,
                "artifact_recommended_action": "clarify",
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
                # WorkerArtifact fields
                "artifact_type": "chart",
                "artifact_status": "failed",
                "artifact_payload": {"error": "No chart generated"},
                "artifact_evidence": {"source": "image_extraction"},
                "artifact_terminal": False,
                "artifact_recommended_action": "clarify",
            }

        return {
            "visualization": {
                "success": True,
                "image_data": image_data,
                "image_format": image_format,
                "code_executed": python_code,
                "execution_time_ms": 0.0,
                "terminal": True,
                "recommended_next_action": "finalize",
            },
            "status": "success",
            # WorkerArtifact fields
            "artifact_type": "chart",
            "artifact_status": "success",
            "artifact_payload": {
                "image_data": image_data,
                "image_format": image_format,
                "chart_type": "unknown",  # Would need LLM to determine
                "normalized_rows": len(raw_data),
            },
            "artifact_evidence": {
                "source": "inline_data",
                "normalized_rows": len(raw_data),
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


# Backward compatibility alias
standalone_visualization_worker = inline_data_worker
