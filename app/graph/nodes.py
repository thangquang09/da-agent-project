from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.config import load_settings
from app.graph.state import AgentState
from app.llm import LLMClient
from app.logger import logger
from app.observability import get_current_tracer
from app.prompts import (
    ANALYSIS_PROMPT_DEFINITION,
    prompt_manager,
    ROUTER_PROMPT_DEFINITION,
)
from app.tools import (
    get_schema_overview,
    query_sql,
    retrieve_business_context,
    retrieve_metric_definition,
    validate_sql,
)
from app.tools.mcp_client import call_mcp_tool



def _extract_first_json_object(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


def _generate_data_summary(rows: list[dict[str, Any]], query: str) -> str:
    """Generate a meaningful summary from query results when LLM analysis fails."""
    if not rows:
        return "No data returned from query."

    if len(rows) == 1:
        # Single row result - format the key values
        row = rows[0]
        parts = []
        for key, value in row.items():
            if value is not None:
                # Format numbers nicely
                if isinstance(value, (int, float)):
                    formatted = (
                        f"{value:,}" if isinstance(value, int) else f"{value:,.2f}"
                    )
                    parts.append(f"{key}: {formatted}")
                else:
                    parts.append(f"{key}: {value}")
        return "Result: " + ", ".join(parts) if parts else "Query returned one row."
    else:
        # Multiple rows - show count and sample
        total = len(rows)
        sample_keys = list(rows[0].keys())[:3]  # First 3 columns
        samples = []
        for i, row in enumerate(rows[:3]):
            sample_vals = [f"{k}={row.get(k)}" for k in sample_keys]
            samples.append(" | ".join(sample_vals))

        summary = f"Query returned {total:,} rows."
        if samples:
            summary += f" Sample data: {'; '.join(samples)}"
            if total > 3:
                summary += f" (and {total - 3} more)"
        return summary



def _context_evidence(retrieved_context: list[dict[str, Any]]) -> list[str]:
    if not retrieved_context:
        return []
    evidence: list[str] = []
    for item in retrieved_context[:2]:
        source = item.get("source", "unknown")
        score = item.get("score", 0)
        snippet = str(item.get("text", "")).strip()
        compact = snippet[:180] + ("..." if len(snippet) > 180 else "")
        evidence.append(f"{source} (score={score}): {compact}")
    return evidence


def _generate_natural_response(
    query: str,
    sql_rows: list[dict[str, Any]],
    row_count: int,
    session_context: str = "",
    has_visualization: bool = False,
    summary_stats: dict[str, Any] | None = None,
) -> tuple[str, dict[str, int] | None, float | None]:
    """Use LLM to generate a natural language response from SQL results."""
    if not sql_rows:
        return "Không có dữ liệu nào được tìm thấy.", None, None

    settings = load_settings()
    llm_usage: dict[str, int] | None = None
    llm_cost_usd: float | None = None

    # Build messages with visualization meta-instruction if applicable
    messages = prompt_manager.synthesis_messages(
        query=query,
        results=sql_rows,
        row_count=row_count,
        session_context=session_context,
        summary_stats=summary_stats,
    )

    # Inject meta-instruction if visualization was successfully generated
    if has_visualization:
        # Add system message or modify first message to include meta-instruction
        meta_instruction = """[SYSTEM META: A visualization chart has ALREADY been successfully generated and will be displayed below your text automatically. Do NOT offer to draw a chart. Instead, acknowledge the chart, briefly explain what it shows based on the data, and conclude your answer.]"""

        # Prepend to the user message content
        for msg in messages:
            if msg.get("role") == "user":
                original_content = msg.get("content", "")
                msg["content"] = f"{meta_instruction}\n\n{original_content}"
                break

    try:
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=messages,
            model=settings.model_synthesis,
            temperature=0.3,
            stream=False,
        )
        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        llm_usage = response.get("_usage_normalized")
        llm_cost_usd = response.get("_cost_usd_estimate")

        if content:
            return content, llm_usage, llm_cost_usd
    except Exception as exc:
        logger.warning("Natural language synthesis failed: {error}", error=str(exc))

    # Fallback to data summary if LLM fails
    return _generate_data_summary(sql_rows, query), None, None


def task_planner(state: AgentState) -> AgentState:
    """
    Analyzes user query and decomposes into parallelizable sub-tasks.

    Handles implicit follow-ups by re-using previous SQL when continuity is detected.

    Example:
    Input: "Compare DAU last week vs this week and show top 5 videos by views"
    Output: [
        {"task_id": "1", "type": "sql_query", "query": "Get DAU last week"},
        {"task_id": "2", "type": "sql_query", "query": "Get DAU this week"},
        {"task_id": "3", "type": "sql_query", "query": "Get top 5 videos by views"}
    ]
    """
    query = state["user_query"]
    schema = state.get("schema_context", "")
    target_db_path = state.get("target_db_path", "")
    continuity_context = state.get("continuity_context", {})
    last_action = state.get("last_action", {})

    # Build XML database context for v2 (no standalone get_schema node runs before task_planner)
    xml_database_context = state.get("xml_database_context", "")
    table_contexts = state.get("table_contexts") or {}
    if table_contexts and not xml_database_context:
        try:
            from pathlib import Path as _Path

            from app.tools.get_schema import get_schema_overview as _get_schema_overview
            from app.tools.table_context import (
                TableEntry,
                build_full_xml_context,
                format_schema_columns,
            )

            _db = _Path(target_db_path) if target_db_path else None
            _overview = _get_schema_overview(db_path=_db)
            _entries = [
                TableEntry(
                    table_name=t["table_name"],
                    schema=format_schema_columns(t["columns"]),
                    business_context=table_contexts.get(t["table_name"], ""),
                )
                for t in _overview.get("tables", [])
            ]
            xml_database_context = build_full_xml_context(_entries)
            logger.info(
                "task_planner: built XML context for {n} tables",
                n=len(_entries),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "task_planner: failed to build XML context: {err}", err=str(exc)
            )

    # Handle continuity - reuse previous SQL if detected
    if continuity_context.get("is_continuation"):
        inherited_action = continuity_context.get("inherited_action", {})
        if inherited_action.get("needs_rerun"):
            base_sql = inherited_action.get("base_sql", "")
            add_visualization = inherited_action.get("add_visualization", False)
            parameter_changes = continuity_context.get("parameter_changes", {})

            logger.info(
                "Continuity detected: re-running previous SQL with parameter changes: {changes}",
                changes=parameter_changes,
            )

            # If there's base SQL from previous action, create a task to re-run it
            if base_sql:
                session_context = state.get("session_context", "")
                return {
                    "task_plan": [
                        {
                            "task_id": "1",
                            "type": "sql_query",
                            "query": query,  # User's current query for context
                            "inherited_sql": base_sql,  # Re-use previous SQL
                            "parameter_changes": parameter_changes,
                            "target_db_path": target_db_path,
                            "schema_context": schema,
                            "session_context": session_context,
                            "xml_database_context": xml_database_context,
                            "status": "pending",
                            "requires_visualization": add_visualization,
                        }
                    ],
                    "execution_mode": "linear",
                    "tool_history": [
                        {
                            "tool": "task_planner",
                            "status": "continuity_rerun",
                            "base_sql_length": len(base_sql),
                            "parameter_changes": parameter_changes,
                        }
                    ],
                    "step_count": state.get("step_count", 0) + 1,
                }

    try:
        client = LLMClient.from_env()
        settings = load_settings()
        messages = prompt_manager.task_decomposition_messages(
            query=query,
            schema=schema[:1000],
        )
        response = client.chat_completion(
            messages=messages,
            model=settings.model_task_planner,
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

        parsed = _extract_first_json_object(content)
        if parsed and "tasks" in parsed:
            tasks = parsed["tasks"]
            # Enrich tasks with context
            session_context = state.get("session_context", "")
            for task in tasks:
                task["target_db_path"] = target_db_path
                task["schema_context"] = schema
                task["session_context"] = session_context
                task["xml_database_context"] = xml_database_context
                task["status"] = "pending"

            execution_mode = "parallel" if len(tasks) > 1 else "linear"

            logger.info(
                "Task planning complete: {task_count} tasks, mode={mode}",
                task_count=len(tasks),
                mode=execution_mode,
            )

            return {
                "task_plan": tasks,
                "execution_mode": execution_mode,
                "tool_history": [
                    {
                        "tool": "task_planner",
                        "status": "ok",
                        "task_count": len(tasks),
                        "execution_mode": execution_mode,
                        "token_usage": llm_usage,
                        "cost_usd": llm_cost_usd,
                    }
                ],
                "step_count": state.get("step_count", 0) + 1,
            }
        else:
            logger.warning(
                "Task planner returned invalid JSON: {content}", content=content[:200]
            )
            return _fallback_task_plan(query, target_db_path, schema, state)

    except Exception as exc:
        logger.error("Task planning failed: {error}", error=str(exc))
        return _fallback_task_plan(query, target_db_path, schema, state)


def _fallback_task_plan(
    query: str, target_db_path: str, schema: str, state: AgentState
) -> AgentState:
    """Fallback when task planner fails."""
    session_context = state.get("session_context", "")
    xml_database_context = state.get("xml_database_context", "")
    return {
        "task_plan": [
            {
                "task_id": "1",
                "type": "sql_query",
                "query": query,
                "target_db_path": target_db_path,
                "schema_context": schema,
                "session_context": session_context,
                "xml_database_context": xml_database_context,
                "status": "pending",
            }
        ],
        "execution_mode": "linear",
        "tool_history": [
            {
                "tool": "task_planner",
                "status": "fallback",
                "task_count": 1,
                "execution_mode": "linear",
            }
        ],
        "step_count": state.get("step_count", 0) + 1,
    }


def aggregate_results(state: AgentState) -> AgentState:
    """
    Fan-in: Combine all parallel task results into unified analysis.

    CRITICAL: Flattens task_results back to root state fields that synthesize_answer expects:
    - sql_result (with rows, row_count, columns)
    - generated_sql (joined from all tasks)
    - validated_sql (from primary/first successful task)
    - analysis_result (with summary)
    """
    results = state.get("task_results", [])
    query = state.get("user_query", "")

    if not results:
        return {
            "aggregate_analysis": {"error": "No task results available"},
            "step_count": state.get("step_count", 0) + 1,
            "tool_history": [
                {
                    "tool": "aggregate_results",
                    "status": "failed",
                    "error": "No task results",
                }
            ],
        }

    # Collect all SQL results - include "skipped" status for visualization failures
    successful_results = [
        r for r in results if r.get("status") in ("success", "skipped")
    ]
    failed_results = [r for r in results if r.get("status") == "failed"]

    combined_data = {
        "task_count": len(results),
        "successful_tasks": len(successful_results),
        "failed_tasks": len(failed_results),
        "results_by_task": {
            r["task_id"]: {
                "query": r.get("query", ""),
                "sql": r.get("validated_sql", ""),
                "row_count": r.get("sql_result", {}).get("row_count", 0),
                "data": r.get("sql_result", {}).get("rows", [])[:5],
                "status": r.get("status"),
                "error": r.get("error"),
            }
            for r in results
        },
    }

    # FLATTEN: Extract SQL data from task_results to root state fields
    # This ensures synthesize_answer can access data like in V1
    all_rows: list[dict[str, Any]] = []
    all_sql_statements: list[str] = []
    primary_sql_result: dict[str, Any] | None = None
    primary_validated_sql = ""
    total_row_count = 0
    # Collect visualization data from tasks that have it
    task_visualizations: list[dict[str, Any]] = []
    # Track if this is a standalone visualization task
    has_standalone_viz = False

    for task_result in successful_results:
        task_type = task_result.get("task_type", "sql_query")

        # Handle standalone visualization tasks
        if task_type == "standalone_visualization":
            viz = task_result.get("visualization")
            if viz:
                task_visualizations.append(viz)
                has_standalone_viz = True
            continue

        # Handle SQL tasks
        sql_result = task_result.get("sql_result", {})
        rows = sql_result.get("rows", [])
        row_count = sql_result.get("row_count", 0)
        validated_sql = task_result.get("validated_sql", "")
        generated_sql = task_result.get("generated_sql", "")

        # Collect rows from all successful tasks
        all_rows.extend(rows)
        total_row_count += row_count

        # Collect SQL statements
        sql_to_add = validated_sql or generated_sql
        if sql_to_add:
            all_sql_statements.append(
                f"-- Task {task_result.get('task_id', '?')}\n{sql_to_add}"
            )

        # Collect visualization if present
        viz = task_result.get("visualization")
        if viz:
            task_visualizations.append(viz)

        # Use first successful task as primary (for single-task scenarios)
        if primary_sql_result is None:
            primary_sql_result = sql_result
            primary_validated_sql = validated_sql

    # Build flattened sql_result for root state
    # For multiple tasks: concatenate rows; for single task: preserve original structure
    if len(successful_results) == 1:
        flattened_sql_result = primary_sql_result or {
            "rows": [],
            "row_count": 0,
            "columns": [],
        }
    else:
        # Merge rows from all tasks
        flattened_sql_result = {
            "rows": all_rows,
            "row_count": total_row_count,
            "columns": primary_sql_result.get("columns", [])
            if primary_sql_result
            else [],
            "merged_from_tasks": len(successful_results),
        }

    # Join SQL statements
    joined_sql = "\n\n---\n\n".join(all_sql_statements) if all_sql_statements else ""

    # LLM-based synthesis of combined results
    synthesis_prompt = f"""Synthesize these parallel query results into a cohesive answer.
    
User Query: {query}

Task Results Summary:
- Total tasks: {combined_data["task_count"]}
- Successful: {combined_data["successful_tasks"]}
- Failed: {combined_data["failed_tasks"]}

Results by Task:
{json.dumps(combined_data["results_by_task"], indent=2, default=str)[:2000]}

Provide a unified analysis that:
1. Directly answers the user's original question
2. Compares results where applicable
3. Notes any data quality issues or inconsistencies
4. Is concise and data-driven"""

    llm_usage = None
    llm_cost_usd = None

    try:
        client = LLMClient.from_env()
        settings = load_settings()
        response = client.chat_completion(
            messages=[{"role": "user", "content": synthesis_prompt}],
            model=settings.model_aggregation,
            temperature=0.3,
        )

        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        llm_usage = response.get("_usage_normalized")
        llm_cost_usd = response.get("_cost_usd_estimate")

        analysis = {
            "synthesis": content,
            "task_summary": combined_data,
            "parallel_execution": combined_data["task_count"] > 1,
        }
    except Exception as exc:
        logger.warning("LLM aggregation failed: {error}", error=str(exc))
        analysis = {
            "synthesis": f"Results aggregated from {combined_data['task_count']} parallel queries.",
            "task_summary": combined_data,
            "error": str(exc),
        }

    return {
        # Flattened fields for synthesize_answer compatibility
        "sql_result": flattened_sql_result,
        "generated_sql": joined_sql,
        "validated_sql": primary_validated_sql,
        "analysis_result": {
            "summary": analysis.get("synthesis", ""),
            "trend": "aggregated",
        },
        # Pass through visualization data from tasks that have it
        "visualization": task_visualizations[0] if task_visualizations else None,
        # Original aggregate analysis
        "aggregate_analysis": analysis,
        # Pass through result_ref from first task (for result_store integration)
        "result_ref": successful_results[0].get("result_ref")
        if len(successful_results) == 1
        else None,
        "tool_history": [
            {
                "tool": "aggregate_results",
                "status": "ok",
                "task_count": len(results),
                "successful": combined_data["successful_tasks"],
                "failed": combined_data["failed_tasks"],
                "has_visualization": bool(task_visualizations),
                "token_usage": llm_usage,
                "cost_usd": llm_cost_usd,
            }
        ],
        "step_count": state.get("step_count", 0) + 1,
    }


def process_uploaded_files(state: AgentState) -> AgentState:
    """
    Process uploaded CSV files: validate, profile, and auto-register into database.

    This node runs after context detection and before routing when files are present.
    For each uploaded CSV:
    1. Validate file (size, encoding, delimiter)
    2. Profile data (schema, stats)
    3. Auto-register as table in PostgreSQL database

    Uses session-level caching to avoid re-processing the same files.
    """
    from pathlib import Path
    from tempfile import NamedTemporaryFile

    from app.tools.auto_register import auto_register_csv
    from app.tools.check_table_exists import table_exists
    from app.utils.file_hash import compute_file_hash

    uploaded_file_data = state.get("uploaded_file_data", [])
    file_cache = state.get("file_cache", {})
    if not uploaded_file_data:
        logger.info("No uploaded files to process")
        return {
            "registered_tables": [],
            "skipped_tables": [],
            "table_contexts": {},
            "file_cache": file_cache,
            "step_count": state.get("step_count", 0) + 1,
            "tool_history": [
                {
                    "tool": "process_uploaded_files",
                    "status": "skipped",
                    "reason": "no_files",
                }
            ],
        }

    registered_tables: list[str] = []
    skipped_tables: list[str] = []
    table_contexts: dict[str, str] = {}  # table_name → user-provided context
    tool_history_entries: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for file_info in uploaded_file_data:
        filename = file_info.get("name", "unknown.csv")
        file_bytes = file_info.get("data")
        file_context = file_info.get("context") or ""  # user-provided business context
        if not file_bytes:
            errors.append(
                {
                    "category": "CSV_PROCESSING_ERROR",
                    "message": f"No data for file: {filename}",
                    "file": filename,
                }
            )
            continue

        # Generate cache key
        file_hash = compute_file_hash(file_bytes)
        table_name = Path(filename).stem
        cache_key = f"postgres::{table_name}::{file_hash}"

        # Check session cache first
        if cache_key in file_cache:
            logger.info(
                "Cache hit for {filename} (table: {table}), skipping re-registration",
                filename=filename,
                table=table_name,
            )
            registered_tables.append(table_name)
            skipped_tables.append(table_name)
            table_contexts[table_name] = file_context  # always update context
            tool_history_entries.append(
                {
                    "tool": "auto_register_csv",
                    "status": "cached",
                    "file": filename,
                    "table": table_name,
                    "source": "session_cache",
                }
            )
            continue

        # Check if table exists in DB (might be from previous session)
        if table_exists(table_name):
            logger.info(
                "Table {table} exists in DB, adding to cache",
                table=table_name,
            )
            file_cache[cache_key] = {
                "table_name": table_name,
                "row_count": 0,  # Unknown without full scan
                "columns": 0,  # Unknown without schema inspection
                "cached_at": datetime.now().isoformat(),
                "source": "db_check",
            }
            registered_tables.append(table_name)
            table_contexts[table_name] = file_context  # preserve user context
            skipped_tables.append(table_name)
            tool_history_entries.append(
                {
                    "tool": "auto_register_csv",
                    "status": "cached",
                    "file": filename,
                    "table": table_name,
                    "source": "db_check",
                }
            )
            continue

        # Not cached - proceed with full registration
        try:
            with NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name

            result, error = auto_register_csv(
                file_path=tmp_path,
                table_name=table_name,
            )

            Path(tmp_path).unlink(missing_ok=True)

            if error:
                errors.append(
                    {
                        "category": "CSV_PROCESSING_ERROR",
                        "message": error,
                        "file": filename,
                    }
                )
                tool_history_entries.append(
                    {
                        "tool": "auto_register_csv",
                        "status": "error",
                        "file": filename,
                        "error": error,
                    }
                )
            else:
                registered_tables.append(result.table_name)
                table_contexts[result.table_name] = file_context  # store user context
                # Add to cache
                file_cache[cache_key] = {
                    "table_name": result.table_name,
                    "row_count": result.row_count,
                    "columns": len(result.columns),
                    "cached_at": datetime.now().isoformat(),
                    "source": "registration",
                }
                tool_history_entries.append(
                    {
                        "tool": "auto_register_csv",
                        "status": "ok",
                        "file": filename,
                        "table": result.table_name,
                        "row_count": result.row_count,
                        "columns": len(result.columns),
                    }
                )
                logger.info(
                    "Auto-registered CSV: {file} -> {table} ({rows} rows)",
                    file=filename,
                    table=result.table_name,
                    rows=result.row_count,
                )
        except Exception as exc:
            errors.append(
                {
                    "category": "CSV_PROCESSING_ERROR",
                    "message": str(exc),
                    "file": filename,
                }
            )
            tool_history_entries.append(
                {
                    "tool": "auto_register_csv",
                    "status": "error",
                    "file": filename,
                    "error": str(exc),
                }
            )
            logger.exception("Failed to process CSV file: {file}", file=filename)

    return {
        "registered_tables": registered_tables,
        "file_cache": file_cache,
        "skipped_tables": skipped_tables,
        "table_contexts": table_contexts,
        "errors": errors,
        "step_count": state.get("step_count", 0) + 1,
        "tool_history": tool_history_entries,
    }


# =============================================================================
# V3 Supervisor / Leader Agent
# =============================================================================


def _summarize_tool_result(tool_name: str, result: dict[str, Any]) -> str:
    if tool_name in {"ask_sql_analyst", "ask_sql_analyst_parallel"}:
        return json.dumps(
            {
                "status": result.get("status"),
                "task_count": result.get("task_count"),
                "execution_mode": result.get("execution_mode"),
                "answer_summary": result.get("answer_summary"),
                "row_count": result.get("sql_result", {}).get("row_count", 0),
                "generated_sql": str(result.get("generated_sql", ""))[:800],
                "errors": result.get("errors", []),
            },
            ensure_ascii=False,
            indent=2,
        )
    elif tool_name == "create_visualization":
        # Filter out bytes data that can't be JSON serialized
        viz = result.get("visualization", {})
        return json.dumps(
            {
                "status": result.get("status"),
                "viz_success": viz.get("success"),
                "viz_error": viz.get("error"),
                "image_size": len(viz.get("image_data", b"")) if isinstance(viz.get("image_data"), bytes) else 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    elif tool_name == "retrieve_rag_answer":
        return json.dumps(
            {
                "context_chunks": len(result.get("context", [])),
                "answer_preview": str(result.get("answer", ""))[:300],
            },
            ensure_ascii=False,
            indent=2,
        )
    return json.dumps(result, ensure_ascii=False, indent=2)[:1500]


def _ensure_v3_schema_context(state: AgentState) -> AgentState:
    if state.get("schema_context") and state.get("xml_database_context") is not None:
        return state

    db_path = Path(state["target_db_path"]) if state.get("target_db_path") else None
    overview = get_schema_overview(db_path=db_path)
    schema_context = json.dumps(overview, ensure_ascii=False)

    xml_database_context = state.get("xml_database_context", "")
    table_contexts = state.get("table_contexts") or {}
    if table_contexts and not xml_database_context:
        from app.tools.table_context import (
            TableEntry,
            build_full_xml_context,
            format_schema_columns,
        )

        entries = [
            TableEntry(
                table_name=t["table_name"],
                schema=format_schema_columns(t["columns"]),
                business_context=table_contexts.get(t["table_name"], ""),
            )
            for t in overview.get("tables", [])
        ]
        xml_database_context = build_full_xml_context(entries)

    enriched_state = dict(state)
    enriched_state["schema_context"] = schema_context
    enriched_state["xml_database_context"] = xml_database_context
    return enriched_state


def _should_decompose_sql_query(query: str) -> bool:
    normalized = query.strip().lower()
    if not normalized:
        return False
    markers = [
        "\n\n",
        "\"\n",
        "compare",
        "so sánh",
        " đồng thời ",
        " cùng lúc ",
        " and ",
    ]
    if sum(1 for marker in markers if marker in normalized) >= 2:
        return True
    question_count = normalized.count("?") + normalized.count('"')
    return question_count >= 3


def _normalize_parallel_sql_tasks(
    raw_tasks: Any, default_query: str
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    if not isinstance(raw_tasks, list):
        return normalized
    for idx, item in enumerate(raw_tasks, start=1):
        if not isinstance(item, dict):
            continue
        subquery = str(item.get("query", "")).strip()
        if not subquery:
            continue
        normalized.append(
            {
                "task_id": str(item.get("task_id", idx)),
                "query": subquery,
            }
        )
    if not normalized and default_query.strip():
        normalized.append({"task_id": "1", "query": default_query.strip()})
    return normalized


def _execute_sql_analyst_task(task: dict[str, Any]) -> dict[str, Any]:
    from app.graph.sql_worker_graph import build_sql_worker_graph

    worker = build_sql_worker_graph()
    return worker.invoke(task)


def _dispatch_parallel_sql_tasks(tasks: list[dict[str, str]], runner) -> list[dict[str, Any]]:  # noqa: ANN001
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(len(tasks), 4)) as executor:
        return list(executor.map(runner, tasks))


def _run_traced_substep(
    node_name: str,
    state: dict[str, Any],
    fn: Callable[[], Any],
    observation_type: str = "tool",
    tracer_override: Any | None = None,
    update_for_trace: dict[str, Any] | None = None,
) -> Any:
    tracer = tracer_override or get_current_tracer()
    if tracer is None:
        return fn()
    scope = tracer.start_node(
        node_name=node_name,
        state=state,
        observation_type=observation_type,
    )
    try:
        update = fn()
    except Exception as exc:  # noqa: BLE001
        tracer.end_node(scope, error=exc)
        raise
    traced_update = update_for_trace
    if traced_update is None:
        if isinstance(update, dict):
            traced_update = update
        elif isinstance(update, list):
            traced_update = {
                "status": "ok",
                "task_count": len(update),
            }
        else:
            traced_update = {"result": str(update)}
    tracer.end_node(scope, update=traced_update)
    return update


def ask_sql_analyst_tool(
    state: AgentState, query: str, *, allow_decomposition: bool = True
) -> dict[str, Any]:
    enriched_state = _ensure_v3_schema_context(state)
    base_state: AgentState = {
        "user_query": query,
        "target_db_path": enriched_state.get("target_db_path", ""),
        "schema_context": enriched_state.get("schema_context", ""),
        "session_context": enriched_state.get("session_context", ""),
        "xml_database_context": enriched_state.get("xml_database_context", ""),
        "table_contexts": enriched_state.get("table_contexts", {}),
        "last_action": enriched_state.get("last_action", {}),
        "thread_id": enriched_state.get("thread_id", ""),
        "run_id": enriched_state.get("run_id", ""),
        "step_count": enriched_state.get("step_count", 0),
        "tool_history": [],
    }
    plan_update: AgentState = {"tool_history": []}
    should_decompose = allow_decomposition and _should_decompose_sql_query(query)
    if should_decompose:
        plan_update = _run_traced_substep(
            "sql_analyst_task_planner",
            {"user_query": query, "step_count": enriched_state.get("step_count", 0)},
            lambda: task_planner(base_state),
            observation_type="agent",
        )
        task_plan = plan_update.get("task_plan", [])
    else:
        task_plan = []
    if not task_plan:
        task_plan = [
            {
                "task_id": "1",
                "type": "sql_query",
                "query": query,
                "target_db_path": enriched_state.get("target_db_path", ""),
                "schema_context": enriched_state.get("schema_context", ""),
                "session_context": enriched_state.get("session_context", ""),
                "xml_database_context": enriched_state.get("xml_database_context", ""),
                "status": "pending",
            }
        ]
    for task in task_plan:
        task["run_id"] = enriched_state.get("run_id", "")
        task["thread_id"] = enriched_state.get("thread_id", "")

    results: list[dict[str, Any]]
    if len(task_plan) > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(len(task_plan), 4)) as executor:
            results = list(executor.map(_execute_sql_analyst_task, task_plan))
    else:
        results = [_execute_sql_analyst_task(task_plan[0])]

    subgraph_tool_history: list[dict[str, Any]] = []
    for result in results:
        subgraph_tool_history.extend(result.get("tool_history", []))

    successful_results = [r for r in results if r.get("status") == "success"]
    failed_results = [r for r in results if r.get("status") == "failed"]

    if len(results) > 1:
        aggregate_state: AgentState = {
            "user_query": query,
            "task_results": results,
            "step_count": state.get("step_count", 0),
        }
        aggregate_update = aggregate_results(aggregate_state)
        answer_summary = (
            aggregate_update.get("analysis_result", {}).get("summary")
            or aggregate_update.get("aggregate_analysis", {}).get("synthesis")
            or "SQL analyst completed multiple tasks."
        )
        sql_result = aggregate_update.get("sql_result", {})
        generated_sql = aggregate_update.get("generated_sql", "")
        validated_sql = aggregate_update.get("validated_sql", "")
        result_ref = aggregate_update.get("result_ref")
        visualization = aggregate_update.get("visualization")
        confidence = "high" if successful_results else "low"
        tool_history = (
            plan_update.get("tool_history", [])
            + subgraph_tool_history
            + aggregate_update.get("tool_history", [])
        )
    else:
        result = results[0]
        sql_result = result.get("sql_result", {})
        generated_sql = result.get("generated_sql", "")
        validated_sql = result.get("validated_sql", "")
        result_ref = result.get("result_ref")
        visualization = result.get("visualization")
        if result.get("status") == "success":
            try:
                natural_answer, _, _ = _generate_natural_response(
                    query=query,
                    sql_rows=sql_result.get("rows", []),
                    row_count=sql_result.get("row_count", 0),
                    session_context=enriched_state.get("session_context", ""),
                    has_visualization=bool(
                        visualization
                        and isinstance(visualization, dict)
                        and visualization.get("success")
                    ),
                    summary_stats=result_ref.get("stats")
                    if isinstance(result_ref, dict)
                    else None,
                )
                answer_summary = natural_answer
            except Exception:  # noqa: BLE001
                answer_summary = _generate_data_summary(sql_result.get("rows", []), query)
            confidence = "high" if sql_result.get("rows") else "medium"
        else:
            answer_summary = str(result.get("error", "SQL analyst failed"))
            confidence = "low"
        tool_history = plan_update.get("tool_history", []) + subgraph_tool_history

    errors = [
        {
            "category": "SQL_ANALYST_ERROR",
            "message": str(result.get("error", "Unknown SQL analyst failure")),
        }
        for result in failed_results
    ]

    return {
        "status": "ok" if successful_results else "failed",
        "task_count": len(task_plan),
        "execution_mode": "parallel" if len(task_plan) > 1 else "linear",
        "answer_summary": answer_summary,
        "sql_result": sql_result,
        "generated_sql": generated_sql,
        "validated_sql": validated_sql,
        "result_ref": result_ref,
        "visualization": visualization,
        "tool_history": tool_history,
        "errors": errors,
        "confidence": confidence,
    }


def ask_sql_analyst_parallel_tool(
    state: AgentState, tasks: list[dict[str, str]], parent_query: str
) -> dict[str, Any]:
    normalized_tasks = _normalize_parallel_sql_tasks(tasks, parent_query)
    if not normalized_tasks:
        return {
            "status": "failed",
            "task_count": 0,
            "execution_mode": "parallel",
            "answer_summary": "Không có tác vụ SQL hợp lệ để thực thi.",
            "sql_result": {},
            "generated_sql": "",
            "validated_sql": "",
            "result_ref": None,
            "visualization": None,
            "tool_history": [],
            "errors": [
                {
                    "category": "INVALID_PARALLEL_TASKS",
                    "message": "Leader did not provide valid SQL subtasks.",
                }
            ],
            "confidence": "low",
            "task_results": [],
        }

    tracer = get_current_tracer()

    def _run_subquery(task_item: dict[str, str]) -> dict[str, Any]:
        trace_state = {
            "user_query": task_item["query"],
            "task_id": task_item["task_id"],
            "step_count": state.get("step_count", 0),
            "execution_mode": "parallel",
        }
        result = _run_traced_substep(
            f"leader_sql_task_{task_item['task_id']}",
            trace_state,
            lambda: ask_sql_analyst_tool(
                state, task_item["query"], allow_decomposition=False
            ),
            observation_type="tool",
            tracer_override=tracer,
        )
        return {
            "task_id": task_item["task_id"],
            "query": task_item["query"],
            "status": "success" if result.get("status") == "ok" else "failed",
            "sql_result": result.get("sql_result", {}),
            "generated_sql": result.get("generated_sql", ""),
            "validated_sql": result.get("validated_sql", ""),
            "result_ref": result.get("result_ref"),
            "visualization": result.get("visualization"),
            "error": "; ".join(
                str(item.get("message", "Unknown SQL analyst failure"))
                for item in result.get("errors", [])
            )
            if result.get("status") != "ok"
            else "",
            "tool_history": result.get("tool_history", []),
            "answer_summary": result.get("answer_summary", ""),
            "confidence": result.get("confidence", "medium"),
        }

    task_results = _run_traced_substep(
        "leader_parallel_dispatch",
        {
            "user_query": parent_query,
            "execution_mode": "parallel",
            "task_results": normalized_tasks,
        },
        lambda: _dispatch_parallel_sql_tasks(normalized_tasks, _run_subquery),
        observation_type="tool",
        tracer_override=tracer,
        update_for_trace={
            "status": "ok",
            "execution_mode": "parallel",
            "task_count": len(normalized_tasks),
        },
    )

    aggregate_state: AgentState = {
        "user_query": parent_query,
        "task_results": task_results,
        "step_count": state.get("step_count", 0),
    }
    aggregate_update = _run_traced_substep(
        "leader_parallel_aggregate",
        aggregate_state,
        lambda: aggregate_results(aggregate_state),
        observation_type="chain",
        tracer_override=tracer,
    )
    successful_results = [r for r in task_results if r.get("status") == "success"]
    failed_results = [r for r in task_results if r.get("status") == "failed"]
    aggregate_tool_history = aggregate_update.get("tool_history", [])
    subtool_history: list[dict[str, Any]] = []
    for task_result in task_results:
        subtool_history.extend(task_result.get("tool_history", []))

    answer_summary = (
        aggregate_update.get("analysis_result", {}).get("summary")
        or aggregate_update.get("aggregate_analysis", {}).get("synthesis")
        or "SQL analyst completed multiple tasks."
    )
    return {
        "status": "ok" if successful_results else "failed",
        "task_count": len(normalized_tasks),
        "execution_mode": "parallel",
        "answer_summary": answer_summary,
        "sql_result": aggregate_update.get("sql_result", {}),
        "generated_sql": aggregate_update.get("generated_sql", ""),
        "validated_sql": aggregate_update.get("validated_sql", ""),
        "result_ref": aggregate_update.get("result_ref"),
        "visualization": aggregate_update.get("visualization"),
        "tool_history": subtool_history + aggregate_tool_history,
        "errors": [
            {
                "category": "SQL_ANALYST_ERROR",
                "message": str(task_result.get("error", "Unknown SQL analyst failure")),
                "task_id": task_result.get("task_id"),
            }
            for task_result in failed_results
        ],
        "confidence": "high" if successful_results and not failed_results else "medium",
        "task_results": task_results,
    }


def leader_agent(state: AgentState) -> AgentState:
    state = _ensure_v3_schema_context(state)
    query = state.get("user_query", "")
    session_context = state.get("session_context", "")
    xml_database_context = state.get("xml_database_context", "")
    settings = load_settings()

    scratchpad_entries: list[str] = []
    leader_tool_history: list[dict[str, Any]] = []
    total_token_usage = 0
    total_cost_usd = 0.0
    sql_artifacts: dict[str, Any] = {}
    used_high_level_tools: list[str] = []
    inferred_intent = "unknown"

    for step in range(1, 6):
        messages = prompt_manager.leader_agent_messages(
            query=query,
            session_context=session_context,
            xml_database_context=xml_database_context,
            scratchpad="\n\n".join(scratchpad_entries),
        )

        try:
            client = LLMClient.from_env()
            response = _run_traced_substep(
                f"leader_llm_step_{step}",
                {
                    "user_query": query,
                    "step_count": state.get("step_count", 0) + step,
                    "execution_mode": "leader_loop",
                },
                lambda: client.chat_completion(
                    messages=messages,
                    model=settings.model_leader,
                    temperature=0.0,
                    stream=False,
                ),
                observation_type="generation",
            )
            usage = response.get("_usage_normalized")
            cost = response.get("_cost_usd_estimate")
            if isinstance(usage, dict):
                total_token_usage += int(usage.get("total_tokens", 0) or 0)
            if isinstance(cost, (int, float)):
                total_cost_usd += float(cost)
            content = (
                response.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            parsed = _extract_first_json_object(content)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "V3 leader agent failed, falling back to SQL analyst: {error_type}: {error}",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            parsed = None

        if not parsed:
            break

        action = str(parsed.get("action", "")).strip().lower()
        if action == "final":
            answer = str(parsed.get("answer", "")).strip()
            confidence = str(parsed.get("confidence", "medium")).strip().lower()
            intent = str(parsed.get("intent", inferred_intent or "unknown")).strip().lower()
            if confidence not in {"high", "medium", "low"}:
                confidence = "medium"
            if intent not in {"sql", "rag", "mixed", "unknown"}:
                intent = inferred_intent or "unknown"
            payload = {
                "answer": answer,
                "evidence": [
                    f"intent={intent}",
                    f"rows={sql_artifacts.get('sql_result', {}).get('row_count', 0)}",
                    "context_chunks=0",
                ],
                "confidence": confidence,
                "used_tools": used_high_level_tools,
                "generated_sql": sql_artifacts.get("validated_sql")
                or sql_artifacts.get("generated_sql", ""),
                "error_categories": [
                    str(item.get("category", "UNKNOWN"))
                    for item in sql_artifacts.get("errors", [])
                ],
                "step_count": state.get("step_count", 0) + step,
                "total_token_usage": total_token_usage,
                "total_cost_usd": round(total_cost_usd, 8),
                "context_type": state.get("context_type", "default"),
                "sql_rows": sql_artifacts.get("sql_result", {}).get("rows", []),
                "sql_row_count": sql_artifacts.get("sql_result", {}).get("row_count", 0),
                "visualization": sql_artifacts.get("visualization"),
                "result_metadata": sql_artifacts.get("result_ref"),
            }
            return {
                "final_answer": answer,
                "final_payload": payload,
                "intent": intent,
                "intent_reason": str(parsed.get("reason", "leader_finalized")),
                "errors": sql_artifacts.get("errors", []),
                "confidence": confidence,
                "step_count": state.get("step_count", 0) + step,
                "tool_history": leader_tool_history + sql_artifacts.get("tool_history", []),
                "generated_sql": sql_artifacts.get("generated_sql", ""),
                "validated_sql": sql_artifacts.get("validated_sql", ""),
                "sql_result": sql_artifacts.get("sql_result", {}),
                "visualization": sql_artifacts.get("visualization"),
                "result_ref": sql_artifacts.get("result_ref"),
            }

        if action != "tool":
            break

        tool_name = str(parsed.get("tool", "")).strip()
        tool_args = parsed.get("args", {})
        tool_query = str(tool_args.get("query", query)).strip() or query
        reason = str(parsed.get("reason", "")).strip() or "leader_tool_call"

        if tool_name == "ask_sql_analyst":
            tool_result = _run_traced_substep(
                "leader_tool_ask_sql_analyst",
                {"user_query": tool_query, "step_count": state.get("step_count", 0)},
                lambda tool_query=tool_query: ask_sql_analyst_tool(state, tool_query),
                observation_type="tool",
            )
            sql_artifacts = tool_result
            inferred_intent = "sql" if inferred_intent == "unknown" else inferred_intent
        elif tool_name == "ask_sql_analyst_parallel":
            raw_tasks = tool_args.get("tasks", [])
            normalized_tasks = _normalize_parallel_sql_tasks(raw_tasks, tool_query or query)
            tool_result = _run_traced_substep(
                "leader_tool_ask_sql_analyst_parallel",
                {
                    "user_query": query,
                    "execution_mode": "parallel",
                    "task_results": normalized_tasks,
                },
                lambda normalized_tasks=normalized_tasks, query=query: ask_sql_analyst_parallel_tool(
                    state, normalized_tasks, query
                ),
                observation_type="tool",
            )
            sql_artifacts = tool_result
            inferred_intent = "sql" if inferred_intent == "unknown" else inferred_intent
        elif tool_name == "retrieve_rag_answer":
            from app.tools import retrieve_rag_answer

            tool_result = _run_traced_substep(
                "leader_tool_retrieve_rag_answer",
                {"user_query": tool_query, "step_count": state.get("step_count", 0)},
                lambda tool_query=tool_query: retrieve_rag_answer(
                    query=tool_query,
                    top_k=int(tool_args.get("top_k", 4) or 4),
                ),
                observation_type="retriever",
            )
            inferred_intent = "rag" if inferred_intent == "unknown" else "mixed"
        elif tool_name == "create_visualization":
            from app.graph.standalone_visualization import standalone_visualization_worker

            raw_data = tool_args.get("raw_data", [])
            # If raw_data is not provided, try to extract from query
            if not raw_data:
                # Simple extraction: find numbers in query
                import re

                numbers = re.findall(r"\b\d+\.?\d*\b", tool_query)
                if numbers and any(kw in tool_query.lower() for kw in ["vẽ", "biểu đồ", "chart", "plot", "graph", "đồ thị"]):
                    # Convert to list of dict format for standalone visualization
                    try:
                        # Format as [{"value": 10}, {"value": 20}, {"value": 30}]
                        # or [{"label": "A", "value": 10}, ...] if labels are provided
                        raw_data = [{"value": float(n)} for n in numbers]
                    except ValueError:
                        raw_data = []

            if not raw_data:
                # No data found, return error
                tool_result = {
                    "visualization": {
                        "success": False,
                        "error": "No data provided for visualization. Please provide data values.",
                    },
                    "status": "failed",
                }
            else:
                # Create task state for standalone visualization
                viz_task_state = {
                    "query": tool_query,
                    "raw_data": raw_data if isinstance(raw_data, list) else [raw_data],
                }
                tool_result = _run_traced_substep(
                    "leader_tool_create_visualization",
                    {"user_query": tool_query, "step_count": state.get("step_count", 0)},
                    lambda viz_task_state=viz_task_state: standalone_visualization_worker(
                        viz_task_state
                    ),
                    observation_type="tool",
                )
            # Map visualization result to sql_artifacts format for final answer
            sql_artifacts = {
                "visualization": tool_result.get("visualization"),
                "tool_history": [
                    {
                        "tool": "create_visualization",
                        "status": tool_result.get("status"),
                    }
                ],
            }
            inferred_intent = "sql" if inferred_intent == "unknown" else inferred_intent
        else:
            break

        used_high_level_tools.append(tool_name)
        leader_tool_history.append(
            {
                "tool": tool_name,
                "status": "ok",
                "reason": reason,
                "source": "leader_agent",
            }
        )
        scratchpad_entries.append(
            f"[Step {step}] tool={tool_name}\n{_summarize_tool_result(tool_name, tool_result)}"
        )

    fallback_result = ask_sql_analyst_tool(state, query)
    answer = fallback_result.get("answer_summary", "Không thể hoàn tất phân tích.")
    payload = {
        "answer": answer,
        "evidence": [
            "intent=sql",
            f"rows={fallback_result.get('sql_result', {}).get('row_count', 0)}",
            "context_chunks=0",
        ],
        "confidence": fallback_result.get("confidence", "medium"),
        "used_tools": ["ask_sql_analyst"],
        "generated_sql": fallback_result.get("validated_sql")
        or fallback_result.get("generated_sql", ""),
        "error_categories": [
            str(item.get("category", "UNKNOWN"))
            for item in fallback_result.get("errors", [])
        ],
        "step_count": state.get("step_count", 0) + 1,
        "total_token_usage": total_token_usage,
        "total_cost_usd": round(total_cost_usd, 8),
        "context_type": state.get("context_type", "default"),
        "sql_rows": fallback_result.get("sql_result", {}).get("rows", []),
        "sql_row_count": fallback_result.get("sql_result", {}).get("row_count", 0),
        "visualization": fallback_result.get("visualization"),
        "result_metadata": fallback_result.get("result_ref"),
    }
    return {
        "final_answer": answer,
        "final_payload": payload,
        "intent": "sql",
        "intent_reason": "leader_fallback_sql_analyst",
        "errors": fallback_result.get("errors", []),
        "confidence": fallback_result.get("confidence", "medium"),
        "step_count": state.get("step_count", 0) + 1,
        "tool_history": leader_tool_history + fallback_result.get("tool_history", []),
        "generated_sql": fallback_result.get("generated_sql", ""),
        "validated_sql": fallback_result.get("validated_sql", ""),
        "sql_result": fallback_result.get("sql_result", {}),
        "visualization": fallback_result.get("visualization"),
        "result_ref": fallback_result.get("result_ref"),
    }


# =============================================================================
# Session Memory Nodes
# =============================================================================

MAX_TURNS_BEFORE_SUMMARY = 10
MAX_TURNS_IN_CONTEXT = 5


def inject_session_context(state: AgentState) -> AgentState:
    """
    Inject relevant session context before routing.

    This node runs BEFORE route_intent to provide conversation history
    for better intent classification, especially for follow-up questions.

    Retrieves:
    - Recent conversation turns from SQLite
    - Conversation summary if exists
    - last_action from most recent assistant turn

    Updates state with:
    - session_context: Formatted context for prompt injection
    - conversation_turn: Current turn number
    - last_action: Previous action metadata for leader follow-up handling
    """
    thread_id = state.get("thread_id")
    if not thread_id:
        logger.debug("No thread_id provided, skipping session context injection")
        return {}

    from app.memory.conversation_store import (
        get_conversation_memory_store,
    )

    conv_store = get_conversation_memory_store()

    # Get recent turns and summary
    recent_turns = conv_store.get_recent_turns(thread_id, limit=MAX_TURNS_IN_CONTEXT)
    summary = conv_store.get_summary(thread_id)
    turn_count = conv_store.get_turn_count(thread_id)

    if not recent_turns and not summary:
        logger.debug(
            "No conversation history found for thread: {thread}", thread=thread_id
        )
        return {
            "conversation_turn": 1,  # Starting new conversation
        }

    context_parts: list[str] = []
    last_action: dict[str, Any] | None = None

    # Add summary if exists
    if summary and summary.summary:
        context_parts.append(f"[Conversation Summary]\n{summary.summary}")
        if summary.key_entities:
            context_parts[-1] += (
                f"\n\nKey entities: {', '.join(summary.key_entities[:5])}"
            )

    # Add recent turns
    if recent_turns:
        turns_text = []
        for turn in recent_turns:
            if turn.role == "user":
                turns_text.append(f"User: {turn.content[:300]}")
            else:
                # Assistant turn - use result_summary if available
                content = turn.result_summary or turn.sql_generated or ""
                if content:
                    turns_text.append(f"Assistant: {content[:300]}")
                # Extract last_action from most recent assistant turn
                if turn.last_action_json:
                    try:
                        last_action = json.loads(turn.last_action_json)
                        logger.debug(
                            "Loaded last_action from turn {turn}",
                            turn=turn.turn_number,
                        )
                    except json.JSONDecodeError:
                        logger.warning(
                            "Failed to parse last_action_json from turn {turn}",
                            turn=turn.turn_number,
                        )

        if turns_text:
            context_parts.append("[Recent Turns]\n" + "\n".join(turns_text))

    session_context = "\n\n".join(context_parts)

    logger.info(
        "Injected session context: {turns} turns, {summary_len} chars summary, has_last_action={has_action}",
        turns=len(recent_turns),
        summary_len=len(summary.summary) if summary else 0,
        has_action=last_action is not None,
    )

    result: dict[str, Any] = {
        "session_context": session_context,
        "conversation_turn": turn_count // 2
        + 1,  # Divide by 2 (user+assistant pairs), +1 for current
    }
    if last_action:
        result["last_action"] = last_action

    return result


def compact_and_save_memory(state: AgentState) -> AgentState:
    """
    Save conversation turn and compact if needed.

    This node runs at the END of the graph, after synthesize_answer.

    - Saves current turn to SQLite
    - Generates/updates summary if turn_count > threshold
    """
    thread_id = state.get("thread_id")
    if not thread_id:
        logger.debug("No thread_id provided, skipping memory save")
        return {}

    from app.memory.conversation_store import (
        ConversationMemoryStore,
        ConversationTurn,
        ConversationSummary,
        get_conversation_memory_store,
    )

    user_query = state.get("user_query", "")
    intent = state.get("intent")
    generated_sql = state.get("generated_sql")

    # Get final answer for result_summary
    final_payload = state.get("final_payload", {})
    result_summary = final_payload.get("answer", "")[:500] if final_payload else None

    # Extract entities (metrics, tables mentioned)
    entities = _extract_entities_from_state(state)

    conv_store = get_conversation_memory_store()

    # Get current turn count
    current_turn_count = conv_store.get_turn_count(thread_id)
    turn_number = current_turn_count + 1

    # Save user turn
    user_turn = ConversationTurn(
        thread_id=thread_id,
        turn_number=turn_number,
        role="user",
        content=user_query,
        intent=intent,
        sql_generated=None,
        result_summary=None,
        entities=entities,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    conv_store.save_turn(user_turn)

    # Save assistant turn with last_action_json
    last_action = state.get("last_action", {})
    last_action_json = json.dumps(last_action) if last_action else None

    assistant_turn = ConversationTurn(
        thread_id=thread_id,
        turn_number=turn_number + 1,
        role="assistant",
        content="",
        intent=None,
        sql_generated=generated_sql,
        result_summary=result_summary,
        entities=entities,
        timestamp=datetime.now(timezone.utc).isoformat(),
        last_action_json=last_action_json,
    )
    conv_store.save_turn(assistant_turn)

    # Compact if needed
    total_turns = turn_number + 1
    if total_turns > MAX_TURNS_BEFORE_SUMMARY * 2:
        _compact_conversation(conv_store, thread_id)

    return {"step_count": state.get("step_count", 0) + 1}


def _extract_entities_from_state(state: AgentState) -> list[str]:
    """Extract entities from state (metrics, tables mentioned)."""
    entities = []

    # From schema context - extract table names
    schema_ctx = state.get("schema_context", "")
    if schema_ctx:
        # Simple extraction: look for "Table:" patterns
        table_matches = re.findall(r"Table:\s*(\w+)", schema_ctx)
        entities.extend(table_matches[:3])

    # From SQL
    sql = state.get("generated_sql", "")
    if sql:
        # Extract table names from SQL
        table_matches = re.findall(r"(?:FROM|JOIN)\s+(\w+)", sql, re.IGNORECASE)
        entities.extend(table_matches[:3])

    # From retrieved context
    retrieved = state.get("retrieved_context", [])
    for item in retrieved[:2]:
        source = item.get("source", "")
        if source and source not in entities:
            entities.append(source)

    # Dedupe and limit
    seen = set()
    unique_entities = []
    for e in entities:
        if e.lower() not in seen:
            seen.add(e.lower())
            unique_entities.append(e)
            if len(unique_entities) >= 5:
                break

    return unique_entities


def _compact_conversation(
    conv_store: ConversationMemoryStore,
    thread_id: str,
) -> None:
    """Use LLM to summarize old turns, update summary, and prune old turns."""
    try:
        from app.memory.conversation_store import ConversationSummary

        # Get all turns — the caller already verified total_turns > threshold
        turns = conv_store.get_recent_turns(thread_id, limit=50)
        if not turns:
            return

        # Keep last MAX_TURNS_BEFORE_SUMMARY turns, summarize the rest
        retention_window = MAX_TURNS_BEFORE_SUMMARY
        turns_to_summarize = (
            turns[:-retention_window] if len(turns) > retention_window else []
        )

        if not turns_to_summarize:
            return

        # Build summarization prompt
        turns_text = []
        for turn in turns_to_summarize:
            if turn.role == "user":
                turns_text.append(f"User: {turn.content}")
            elif turn.result_summary:
                turns_text.append(f"Assistant: {turn.result_summary}")

        if not turns_text:
            return

        from app.config import load_settings
        from app.llm import LLMClient

        settings = load_settings()

        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that summarizes conversations concisely. "
                    "Create a brief summary (2-3 sentences) that captures the key topics, questions asked, "
                    "and insights gained. Focus on metrics, data analysis, and SQL queries discussed.",
                },
                {
                    "role": "user",
                    "content": f"Summarize this conversation:\n\n{chr(10).join(turns_text)}",
                },
            ],
            model=settings.default_router_model,
            temperature=0.0,
        )

        summary_text = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

        if summary_text:
            # Extract key entities from all turns
            all_entities = []
            for turn in turns:
                all_entities.extend(turn.entities)
            seen = set()
            key_entities = []
            for e in all_entities:
                if e.lower() not in seen:
                    seen.add(e.lower())
                    key_entities.append(e)

            summary = ConversationSummary(
                thread_id=thread_id,
                summary=summary_text,
                turn_count=len(turns),
                last_updated=datetime.now(timezone.utc).isoformat(),
                key_entities=key_entities[:10],
            )
            conv_store.update_summary(summary)

            # Prune old turns, keeping only the retention window
            conv_store.delete_old_turns(thread_id, keep_last_n=retention_window)

            logger.info(
                "Compacted conversation: thread={thread}, summarized={summarized}, kept={kept}",
                thread=thread_id,
                summarized=len(turns_to_summarize),
                kept=retention_window,
            )

    except Exception as exc:
        logger.warning("Failed to compact conversation: {error}", error=str(exc))


# =============================================================================
# Continuity Detection - Memory of Action
# =============================================================================


def capture_action_node(state: AgentState) -> AgentState:
    """
    Capture completed action for future continuity detection.

    This node runs AFTER synthesize_answer to save action metadata.

    Captures:
    - action_type: sql/rag/mixed/unknown
    - generated_sql: The SQL that was executed
    - parameters: Extracted parameters from query
    - result_summary: Lightweight summary (NOT raw data)

    Does NOT capture:
    - Raw SQL result rows (too large)
    - Full conversation context (already in session memory)
    """
    from app.graph.continuity import (
        extract_parameters_from_state,
        summarize_result_for_context,
    )

    intent = state.get("intent", "unknown")
    generated_sql = state.get("generated_sql", "") or state.get("validated_sql", "")
    final_payload = state.get("final_payload", {})

    # Only capture successful actions
    confidence = state.get("confidence", "low")
    if confidence not in ("high", "medium"):
        logger.debug(
            "Skipping action capture for low confidence: confidence={conf}",
            conf=confidence,
        )
        return {"last_action": {}}

    # Build last_action
    last_action = {
        "action_type": intent,
        "intent": intent,
        "generated_sql": generated_sql,
        "parameters": extract_parameters_from_state(state),
        "result_summary": summarize_result_for_context(state.get("sql_result", {})),
        "has_visualization": bool(state.get("visualization")),
    }

    # Add visualization type if present
    viz = state.get("visualization", {})
    if viz and viz.get("success"):
        last_action["visualization_type"] = "generated"

    # Add answer snippet
    answer = final_payload.get("answer", "")
    if answer:
        last_action["answer_snippet"] = answer[:300]

    logger.info(
        "Captured action: type={type}, has_sql={has_sql}, has_viz={has_viz}",
        type=intent,
        has_sql=bool(generated_sql),
        has_viz=last_action.get("has_visualization", False),
    )

    return {"last_action": last_action}
