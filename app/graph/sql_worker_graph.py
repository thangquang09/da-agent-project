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
            model=settings.default_router_model,
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
        logger.exception("SQL execution failed in worker")
        return {
            "status": "failed",
            "error": str(exc),
            "sql_result": {"error": str(exc), "rows": [], "row_count": 0},
        }


def build_sql_worker_graph():
    """
    Subgraph for executing a single SQL task.

    This is invoked in parallel via the Send API from the main graph.
    The subgraph operates on TaskState and returns updates (not full state)
    to avoid conflicts during parallel execution.
    """
    builder = StateGraph(TaskState)

    # Add nodes for the worker pipeline
    builder.add_node("get_schema", _task_get_schema)
    builder.add_node("generate_sql", _task_generate_sql)
    builder.add_node("validate_sql", _task_validate_sql)
    builder.add_node("execute_sql", _task_execute_sql)

    # Define edges
    builder.add_edge(START, "get_schema")
    builder.add_edge("get_schema", "generate_sql")
    builder.add_edge("generate_sql", "validate_sql")
    builder.add_edge("validate_sql", "execute_sql")
    builder.add_edge("execute_sql", END)

    return builder.compile()


# Singleton instance
_sql_worker_graph = None


def get_sql_worker_graph():
    """Get or create the SQL worker subgraph singleton."""
    global _sql_worker_graph
    if _sql_worker_graph is None:
        _sql_worker_graph = build_sql_worker_graph()
    return _sql_worker_graph
