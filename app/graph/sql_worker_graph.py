from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.config import load_settings
from app.graph.state import TaskState
from app.llm import LLMClient
from app.logger import logger
from app.prompts import prompt_manager
from app.tools import query_sql, validate_sql
from app.tools.visualization import (
    get_visualization_service,
    is_visualization_available,
)


def _format_sql_error(error_msg: str) -> str:
    """
    Convert raw SQL error messages into user-friendly explanations.
    Prevents leaking internal database details.
    """
    error_lower = error_msg.lower()

    # Column-related errors
    if "no such column" in error_lower:
        import re

        match = re.search(r"no such column: (\w+)", error_msg, re.IGNORECASE)
        if match:
            column = match.group(1)
            return f"The query references a column '{column}' that doesn't exist in the database. Please check the available columns and try again."
        return "The query references a column that doesn't exist in the database. Please check the available columns and try again."

    # Table-related errors
    if "no such table" in error_lower:
        import re

        match = re.search(r"no such table: (\w+)", error_msg, re.IGNORECASE)
        if match:
            table = match.group(1)
            return f"The query references a table '{table}' that doesn't exist in the database."
        return "The query references a table that doesn't exist in the database."

    # Syntax errors
    if "syntax error" in error_lower:
        return "The SQL query has a syntax error. Please check the query structure."

    # Generic error - don't leak raw message
    return "An error occurred while executing the query. The data may not be available or the query needs adjustment."


def _apply_parameter_changes(sql: str, parameter_changes: dict[str, Any]) -> str:
    """
    Apply parameter changes to inherited SQL.

    This is a simple string-based approach for common patterns:
    - Replace WHERE condition values
    - Update column selections

    For complex changes, the SQL should be regenerated.
    """
    if not parameter_changes:
        return sql

    modified_sql = sql

    # Try to apply simple parameter replacements
    # Example: {"addiction_level": "Medium"} → replace 'High' with 'Medium' in WHERE
    for param_name, new_value in parameter_changes.items():
        # Pattern: column = 'value' or column='value'
        pattern = rf"({param_name}\s*=\s*)'[^']*'(?=\s|$|AND|OR|\))"
        replacement = rf"\1'{new_value}'"
        modified_sql = re.sub(pattern, replacement, modified_sql, flags=re.IGNORECASE)

    return modified_sql


def _task_get_schema(task_state: TaskState) -> dict[str, Any]:
    """Get schema for a specific task. Reuse schema_context from task_planner if available."""
    existing_schema = task_state.get("schema_context", "")
    if existing_schema:
        return {
            "schema_context": existing_schema,
            "status": "running",
            "tool_history": [
                {
                    "tool": "get_schema",
                    "status": "reused",
                    "source": "task_planner",
                }
            ],
        }

    db_path = task_state.get("target_db_path")
    from app.tools import get_schema_overview

    try:
        overview = get_schema_overview(db_path=Path(db_path) if db_path else None)
        schema = str(overview)
        table_count = len(overview.get("tables", []))
    except Exception as exc:
        logger.warning("Failed to get schema in worker: {error}", error=str(exc))
        schema = ""
        table_count = 0

    return {
        "schema_context": schema,
        "status": "running",
        "tool_history": [
            {
                "tool": "get_schema",
                "status": "ok",
                "table_count": table_count,
            }
        ],
    }


def _task_generate_sql(task_state: TaskState) -> dict[str, Any]:
    """Generate SQL for a specific task. Re-use inherited SQL if continuity is detected."""
    query = task_state.get("query", "")
    schema = task_state.get("schema_context", "")
    session_context = task_state.get("session_context", "")
    inherited_sql = task_state.get("inherited_sql")
    parameter_changes = task_state.get("parameter_changes", {})

    # If continuity detected and we have inherited SQL, re-use it
    if inherited_sql:
        logger.info(
            "Using inherited SQL from continuity context (length={len_sql})",
            len_sql=len(inherited_sql),
        )

        # Apply parameter changes if any
        if parameter_changes:
            sql = _apply_parameter_changes(inherited_sql, parameter_changes)
            logger.info(
                "Applied parameter changes to inherited SQL: {changes}",
                changes=parameter_changes,
            )
        else:
            sql = inherited_sql

        return {
            "generated_sql": sql,
            "status": "running",
            "tool_history": [
                {
                    "tool": "generate_sql",
                    "status": "inherited",
                    "source": "continuity",
                }
            ],
        }

    # Normal flow: generate SQL via LLM
    settings = load_settings()
    sql = ""
    llm_usage = None
    llm_cost_usd = None

    try:
        client = LLMClient.from_env()
        messages = prompt_manager.sql_worker_messages(
            query=query,
            schema=schema[:1500],
            session_context=session_context,
            xml_database_context=task_state.get("xml_database_context", ""),
        )
        response = client.chat_completion(
            messages=messages,
            model=settings.model_sql_generation,
            temperature=0.0,
        )

        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        llm_usage = response.get("_usage_normalized")
        llm_cost_usd = response.get("_cost_usd_estimate")

        # Extract SQL from markdown if present
        fenced_match = re.search(
            r"```(?:sql)?\s*(.*?)```", content, re.DOTALL | re.IGNORECASE
        )
        if fenced_match:
            sql = fenced_match.group(1).strip()
        else:
            # Take from first SELECT or WITH
            statement_match = re.search(
                r"\b(SELECT|WITH)\b[\s\S]*", content, re.IGNORECASE
            )
            if statement_match:
                sql = statement_match.group(0).strip()
            else:
                sql = content

    except Exception as exc:
        logger.error("SQL generation failed in worker: {error}", error=str(exc))
        sql = ""

    return {
        "generated_sql": sql,
        "status": "ok" if sql else "failed",
        "tool_history": [
            {
                "tool": "generate_sql",
                "status": "ok" if sql else "failed",
                "sql_length": len(sql),
                "token_usage": llm_usage,
                "cost_usd": llm_cost_usd,
            }
        ],
    }


def _task_validate_sql(task_state: TaskState) -> dict[str, Any]:
    """Validate SQL for a specific task."""
    sql = task_state.get("generated_sql", "")
    db_path = task_state.get("target_db_path")

    if not sql:
        return {
            "status": "failed",
            "error": "No SQL generated",
            "tool_history": [
                {
                    "tool": "validate_sql",
                    "status": "failed",
                    "reason": "no_sql",
                }
            ],
        }

    result = validate_sql(
        sql, db_path=Path(db_path) if db_path else None, max_limit=200
    )

    if not result.is_valid:
        return {
            "status": "failed",
            "error": "; ".join(result.reasons),
            "validated_sql": result.sanitized_sql,
            "tool_history": [
                {
                    "tool": "validate_sql",
                    "status": "failed",
                    "reasons": result.reasons,
                }
            ],
        }

    return {
        "validated_sql": result.sanitized_sql,
        "tool_history": [
            {
                "tool": "validate_sql",
                "status": "ok",
            }
        ],
    }


def _task_execute_sql(task_state: TaskState) -> dict[str, Any]:
    """Execute SQL for a specific task."""
    sql = task_state.get("validated_sql", "")
    db_path = task_state.get("target_db_path")

    if not sql:
        return {
            "status": "failed",
            "error": "No validated SQL to execute",
            "sql_result": {"error": "No SQL", "rows": [], "row_count": 0},
        }

    try:
        result = query_sql(sql, db_path=Path(db_path) if db_path else None)

        # Persist to result_store
        result_ref = None
        try:
            from app.tools.result_store import get_result_store

            store = get_result_store()
            result_ref = store.save_result(
                sql=sql,
                sql_result=result,
                run_id=task_state.get("run_id"),
                thread_id=task_state.get("thread_id"),
                db_path=str(db_path) if db_path else None,
            )
        except Exception as exc:
            logger.warning(
                "Failed to save result to result_store: {error}", error=str(exc)
            )

        return {
            "sql_result": result,
            "status": "success",
            "execution_time_ms": result.get("latency_ms", 0),
            "result_ref": result_ref,
            "tool_history": [
                {
                    "tool": "execute_sql",
                    "status": "ok",
                    "row_count": result.get("row_count", 0),
                    "latency_ms": result.get("latency_ms", 0),
                }
            ],
        }
    except Exception as exc:
        # Log error without full stack trace to avoid leaking internal details
        error_msg = str(exc)
        logger.error(
            "SQL execution failed in worker (task_id={task_id}): {error}",
            task_id=task_state.get("task_id", "unknown"),
            error=error_msg,
        )
        # Return user-friendly error message
        user_friendly_error = _format_sql_error(error_msg)
        return {
            "status": "failed",
            "error": user_friendly_error,
            "sql_result": {"error": user_friendly_error, "rows": [], "row_count": 0},
            "tool_history": [
                {
                    "tool": "execute_sql",
                    "status": "failed",
                    "error": user_friendly_error,
                }
            ],
        }


def _task_generate_visualization(task_state: TaskState) -> dict[str, Any]:
    """Generate visualization for task results using E2B sandbox.

    This runs nested within the SQL worker after execute_sql, ensuring
    the SQL data is already available before visualization is attempted.

    Uses LLM-based code generation with model_sql_generation. Falls back to
    rule-based templates only if LLM code generation or execution fails.
    """
    query = task_state.get("query", "")
    sql_result = task_state.get("sql_result", {})
    rows = sql_result.get("rows", [])

    if not rows:
        return {
            "visualization": {
                "success": False,
                "error": "No data available for visualization",
            },
            "status": "failed",
        }

    if not is_visualization_available():
        logger.warning("Visualization not available - E2B not configured")
        return {
            "visualization": {
                "success": False,
                "error": "Visualization service not available (E2B not configured)",
            },
            "status": "success",  # Keep success so task results are not dropped
        }

    # Step 1: Generate Python visualization code using LLM (preferred)
    python_code = _generate_visualization_code_llm(query, rows)

    # If LLM failed to generate code, fall back to template
    if not python_code:
        logger.warning("LLM code generation failed, falling back to template")
        python_code = _generate_chart_code_template(query, rows)

    # Step 2: Execute visualization in E2B sandbox
    service = get_visualization_service()

    try:
        result = service.generate_visualization(
            data_rows=rows,
            user_query=query,
            python_code=python_code,
        )

        # If LLM code failed but template might succeed, try template as fallback
        if not result.success and python_code != _generate_chart_code_template(
            query, rows
        ):
            logger.warning("LLM code execution failed, trying template fallback")
            template_code = _generate_chart_code_template(query, rows)
            result = service.generate_visualization(
                data_rows=rows,
                user_query=query,
                python_code=template_code,
            )

        return {
            "visualization": {
                "success": result.success,
                "image_data": result.image_data,
                "image_format": result.image_format,
                "error": result.error,
                "code_executed": result.code_executed,
                "execution_time_ms": result.execution_time_ms,
            },
            "status": "success" if result.success else "failed",
        }

    except Exception as exc:
        logger.exception("Visualization generation failed in worker")
        # Last resort: try template code
        try:
            template_code = _generate_chart_code_template(query, rows)
            result = service.generate_visualization(
                data_rows=rows,
                user_query=query,
                python_code=template_code,
            )
            return {
                "visualization": {
                    "success": result.success,
                    "image_data": result.image_data,
                    "image_format": result.image_format,
                    "error": result.error if not result.success else None,
                    "code_executed": result.code_executed,
                    "execution_time_ms": result.execution_time_ms,
                },
                "status": "success" if result.success else "failed",
            }
        except Exception as exc2:
            logger.exception("Template fallback also failed")
            return {
                "visualization": {
                    "success": False,
                    "error": f"Primary: {exc}; Fallback: {exc2}",
                },
                "status": "failed",
            }


def _generate_visualization_code_llm(query: str, data_rows: list[dict]) -> str | None:
    """Generate Python visualization code using LLM with model_sql_generation.

    This uses the LLM to understand chart type requirements from user query
    instead of relying on rule-based templates. Uses model_sql_generation
    for better code quality.
    """
    if not data_rows:
        return None

    # Build schema description
    columns = list(data_rows[0].keys())
    schema_desc = f"Columns: {', '.join(columns)}\n"
    schema_desc += f"Sample data (first {min(3, len(data_rows))} rows):\n"
    for i, row in enumerate(data_rows[:3]):
        schema_desc += f"  Row {i + 1}: {row}\n"

    try:
        settings = load_settings()
        client = LLMClient.from_env()
        messages = prompt_manager.visualization_messages(
            query=query,
            schema_desc=schema_desc,
        )

        # Use model_sql_generation as requested
        response = client.chat_completion(
            messages=messages,
            model=settings.model_sql_generation,
            temperature=0.2,
        )

        code = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

        # Clean up code (remove markdown fences if present)
        code = re.sub(r"^```python\s*", "", code, flags=re.IGNORECASE)
        code = re.sub(r"^```\s*", "", code, flags=re.IGNORECASE)
        code = re.sub(r"```$", "", code, flags=re.IGNORECASE)
        code = code.strip()

        if code and "plt.show()" in code:
            logger.info(
                "Generated visualization code via LLM for query: {query}",
                query=query[:50],
            )
            return code
        else:
            logger.warning("LLM code missing plt.show(), falling back to template")
            return None

    except Exception as exc:
        logger.warning(
            "LLM visualization code generation failed: {error}", error=str(exc)
        )
        return None


def _generate_chart_code_template(query: str, data_rows: list[dict]) -> str:
    """Generate basic Python visualization code using rule-based templates.

    Used as a fallback when LLM code generation or execution fails.
    """
    if not data_rows:
        return ""

    columns = list(data_rows[0].keys())

    # Detect chart type from query
    query_lower = query.lower()
    if any(kw in query_lower for kw in ["bar", "cột", "column"]):
        chart_type = "bar"
    elif any(kw in query_lower for kw in ["line", "đường", "trend", "trending"]):
        chart_type = "line"
    elif any(
        kw in query_lower for kw in ["scatter", "phân tán", "phân bố", "correlation"]
    ):
        chart_type = "scatter"
    elif any(kw in query_lower for kw in ["pie", "tròn", "bánh"]):
        chart_type = "pie"
    else:
        # Default: try to auto-detect based on data
        chart_type = "auto"

    # Build code
    code_lines = [
        "import pandas as pd",
        "import matplotlib.pyplot as plt",
        "import seaborn as sns",
        "import numpy as np",
        "",
        "# Read data",
        "df = pd.read_csv('/home/user/query_data.csv')",
        "",
        "# Set style",
        "sns.set_style('whitegrid')",
        "plt.figure(figsize=(12, 6))",
        "",
    ]

    # Add chart-specific code
    if chart_type == "bar" or (chart_type == "auto" and len(columns) >= 2):
        # Try to identify categorical and numeric columns
        code_lines.extend(
            [
                "# Bar chart",
                f"x_col = '{columns[0]}'",
                f"y_col = '{columns[1]}' if len(df.columns) > 1 else '{columns[0]}'",
                "sns.barplot(data=df, x=x_col, y=y_col, palette='viridis')",
                "plt.title('Data Visualization')",
                "plt.xticks(rotation=45, ha='right')",
                "plt.tight_layout()",
            ]
        )
    elif chart_type == "line":
        code_lines.extend(
            [
                "# Line chart",
                f"x_col = '{columns[0]}'",
                f"y_col = '{columns[1]}' if len(df.columns) > 1 else '{columns[0]}'",
                "sns.lineplot(data=df, x=x_col, y=y_col, marker='o')",
                "plt.title('Trend Visualization')",
                "plt.xticks(rotation=45, ha='right')",
                "plt.tight_layout()",
            ]
        )
    elif chart_type == "scatter":
        code_lines.extend(
            [
                "# Scatter plot",
                f"x_col = '{columns[0]}'",
                f"y_col = '{columns[1]}' if len(df.columns) > 1 else '{columns[0]}'",
                "sns.scatterplot(data=df, x=x_col, y=y_col, s=100)",
                "plt.title('Scatter Plot')",
                "plt.tight_layout()",
            ]
        )
    else:
        # Generic visualization
        code_lines.extend(
            [
                "# Generic data visualization",
                "if len(df.columns) >= 2:",
                f"    sns.barplot(data=df, x='{columns[0]}', y='{columns[1]}', palette='viridis')",
                "else:",
                f"    df['{columns[0]}'].plot(kind='bar')",
                "plt.title('Data Visualization')",
                "plt.xticks(rotation=45, ha='right')",
                "plt.tight_layout()",
            ]
        )

    code_lines.append("plt.show()")

    return "\n".join(code_lines)


def _should_visualize(task_state: TaskState) -> bool:
    """Determine if visualization should run based on task state.

    Returns True if:
    - task has requires_visualization flag set
    - previous execution was successful
    """
    return bool(
        task_state.get("requires_visualization")
        and task_state.get("status") == "success"
    )


def build_sql_worker_graph():
    """
    Subgraph for executing a single SQL task.

    This is invoked in parallel via the Send API from the main graph.
    The subgraph operates on TaskState and returns updates (not full state)
    to avoid conflicts during parallel execution.

    Visualization is handled nested within this subgraph after execute_sql
    if the task has requires_visualization=True and status=success.
    """
    builder = StateGraph(TaskState)

    # Add nodes for the worker pipeline
    builder.add_node("get_schema", _task_get_schema)
    builder.add_node("generate_sql", _task_generate_sql)
    builder.add_node("validate_sql", _task_validate_sql)
    builder.add_node("execute_sql", _task_execute_sql)
    builder.add_node("generate_visualization", _task_generate_visualization)

    # Define edges
    builder.add_edge(START, "get_schema")
    builder.add_edge("get_schema", "generate_sql")
    builder.add_edge("generate_sql", "validate_sql")
    builder.add_edge("validate_sql", "execute_sql")

    # Conditional routing for visualization
    # If requires_visualization=True AND status=success -> generate_visualization -> END
    # Otherwise -> END
    builder.add_conditional_edges(
        "execute_sql",
        _should_visualize,
        {
            True: "generate_visualization",
            False: END,
        },
    )
    builder.add_edge("generate_visualization", END)

    return builder.compile()


# Singleton instance
_sql_worker_graph = None


def get_sql_worker_graph():
    """Get or create the SQL worker subgraph singleton."""
    global _sql_worker_graph
    if _sql_worker_graph is None:
        _sql_worker_graph = build_sql_worker_graph()
    return _sql_worker_graph
