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


def _task_get_schema(task_state: TaskState) -> dict[str, Any]:
    """Get schema for a specific task."""
    db_path = task_state.get("target_db_path")
    from app.tools import get_schema_overview

    try:
        overview = get_schema_overview(db_path=Path(db_path) if db_path else None)
        schema = str(overview)
    except Exception as exc:
        logger.warning("Failed to get schema in worker: {error}", error=str(exc))
        schema = task_state.get("schema_context", "")

    # Only return fields that need to be updated
    return {
        "schema_context": schema,
        "status": "running",
    }


def _task_generate_sql(task_state: TaskState) -> dict[str, Any]:
    """Generate SQL for a specific task."""
    query = task_state.get("query", "")
    schema = task_state.get("schema_context", "")

    settings = load_settings()
    sql = ""

    try:
        client = LLMClient.from_env()

        system_prompt = """You are a SQL expert. Generate a read-only SQL query to answer the user's question.
Use the provided schema. Only use SELECT and WITH statements.
Respond with ONLY the SQL query, no explanations."""

        response = client.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"Schema: {schema[:1500]}\n\nQuestion: {query}\n\nGenerate SQL:",
                },
            ],
            model=settings.model_sql_generation,
            temperature=0.0,
        )

        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

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

    return {"generated_sql": sql}


def _task_validate_sql(task_state: TaskState) -> dict[str, Any]:
    """Validate SQL for a specific task."""
    sql = task_state.get("generated_sql", "")
    db_path = task_state.get("target_db_path")

    if not sql:
        return {
            "status": "failed",
            "error": "No SQL generated",
        }

    result = validate_sql(
        sql, db_path=Path(db_path) if db_path else None, max_limit=200
    )

    if not result.is_valid:
        return {
            "status": "failed",
            "error": "; ".join(result.reasons),
            "validated_sql": result.sanitized_sql,
        }

    return {"validated_sql": result.sanitized_sql}


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

        return {
            "sql_result": result,
            "status": "success",
            "execution_time_ms": result.get("latency_ms", 0),
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
        }


def _task_generate_visualization(task_state: TaskState) -> dict[str, Any]:
    """Generate visualization for task results using E2B sandbox.

    This runs nested within the SQL worker after execute_sql, ensuring
    the SQL data is already available before visualization is attempted.

    Uses LLM-based code generation to understand chart type requirements
    from the user query instead of rule-based templates.
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
            "status": "skipped",
        }

    try:
        # Step 1: Generate Python visualization code using LLM
        python_code = _generate_visualization_code_llm(query, rows)

        # Step 2: Execute visualization in E2B sandbox
        service = get_visualization_service()
        result = service.generate_visualization(
            data_rows=rows,
            user_query=query,
            python_code=python_code,
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
        return {
            "visualization": {
                "success": False,
                "error": str(exc),
            },
            "status": "failed",
        }


def _generate_visualization_code_llm(query: str, data_rows: list[dict]) -> str | None:
    """Generate Python visualization code using LLM.

    This replaces rule-based templates with LLM understanding of:
    - Chart type from user query (bar chart, line chart, etc.)
    - Data schema and column selection
    - Proper seaborn/matplotlib usage
    """
    if not data_rows:
        return None

    # Build schema description
    columns = list(data_rows[0].keys())
    schema_desc = f"Columns: {', '.join(columns)}\n"
    schema_desc += f"Sample data (first {min(3, len(data_rows))} rows):\n"
    for i, row in enumerate(data_rows[:3]):
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
        code = re.sub(r"^```python\s*", "", code)
        code = re.sub(r"^```\s*", "", code)
        code = re.sub(r"```$", "", code)
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
