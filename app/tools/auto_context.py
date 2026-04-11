from __future__ import annotations

import json
from typing import Any

from app.config import load_settings
from app.llm import LLMClient
from app.logger import logger
from app.tools.get_schema import describe_table
from app.tools.query_sql import query_sql
from app.tools.table_metadata import get_table_context, set_table_context


def _sample_table_data(table_name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch 10 sample rows and column info for a table.

    Returns:
        (sample_rows, columns_info) where columns_info has name + type per column.
    """
    # Sample rows
    sample_sql = f'SELECT * FROM "{table_name}" ORDER BY RANDOM() LIMIT 10'
    sample_result = query_sql(sample_sql)
    sample_rows = sample_result.get("rows", [])

    # Column info
    col_infos = describe_table(table_name)
    columns_info = [
        {"name": c.name, "type": c.col_type}
        for c in col_infos
    ]

    return sample_rows, columns_info


def _format_columns(columns_info: list[dict[str, Any]]) -> str:
    """Format column list for the prompt."""
    lines = []
    for col in columns_info[:20]:
        lines.append(f"- {col['name']} ({col['type']})")
    return "\n".join(lines)


def _format_sample_rows(rows: list[dict[str, Any]]) -> str:
    """Format sample rows as a readable table for the prompt."""
    if not rows:
        return "(no data)"
    # Show max 5 rows, max 8 columns for compactness
    limited = rows[:5]
    cols = list(limited[0].keys())[:8]
    lines = [" | ".join(cols)]
    lines.append("-" * len(lines[0]))
    for row in limited:
        vals = [str(row.get(c, ""))[:30] for c in cols]
        lines.append(" | ".join(vals))
    return "\n".join(lines)


def auto_generate_table_context(table_name: str) -> str | None:
    """Auto-generate business context for a table using LLM.

    Samples 10 random rows + schema → LLM → 1-2 sentence domain description.
    Returns the generated context string, or None on failure.
    """
    # Skip if context already exists
    existing = get_table_context(table_name)
    if existing and len(existing.strip()) > 10:
        logger.info(
            "auto_context: table={table} already has context, skipping",
            table=table_name,
        )
        return existing.strip()

    try:
        sample_rows, columns_info = _sample_table_data(table_name)
    except Exception as exc:
        logger.warning(
            "auto_context: failed to sample table={table}: {error}",
            table=table_name,
            error=str(exc),
        )
        return None

    columns_text = _format_columns(columns_info)
    rows_text = _format_sample_rows(sample_rows)

    settings = load_settings()

    # Build prompt from definition
    from app.prompts.auto_context import AUTO_CONTEXT_PROMPT_DEFINITION

    messages = []
    for msg in AUTO_CONTEXT_PROMPT_DEFINITION.messages:
        content = msg["content"]
        content = content.replace("{{table_name}}", table_name)
        content = content.replace("{{columns_info}}", columns_text)
        content = content.replace("{{sample_rows}}", rows_text)
        messages.append({"role": msg["role"], "content": content})

    try:
        client = LLMClient.from_env()
        # Use a lighter model for this task
        model = getattr(settings, "model_preclassifier", settings.default_router_model)
        response = client.chat_completion(
            messages=messages,
            model=model,
            temperature=0.3,
            stream=False,
        )
        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

        if not content or len(content) < 10:
            logger.warning(
                "auto_context: LLM returned empty/short response for table={table}",
                table=table_name,
            )
            return None

        logger.info(
            "auto_context: generated for table={table}: {preview}",
            table=table_name,
            preview=content[:120],
        )
        return content

    except Exception as exc:
        logger.warning(
            "auto_context: LLM call failed for table={table}: {error}",
            table=table_name,
            error=str(exc),
        )
        return None


def auto_generate_and_persist(table_name: str) -> str | None:
    """Auto-generate context and persist it. Returns the context or None."""
    context = auto_generate_table_context(table_name)
    if context:
        set_table_context(table_name, context)
    return context
