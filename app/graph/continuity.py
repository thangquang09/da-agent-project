"""Continuity detection for implicit follow-up handling.

This module handles the detection of implicit follow-up queries where users
modify parameters or request actions based on previous results without
explicitly stating the full query.

Example:
    Turn 1: "Vẽ biểu đồ cho addiction_level='High'"
    Turn 2: "Đổi sang Medium"  # Implicit follow-up
    Turn 3: "Vẽ biểu đồ cho kết quả vừa rồi"  # Needs SQL re-run
"""

from __future__ import annotations

import json
from typing import Any

from app.config import load_settings
from app.llm import LLMClient
from app.logger import logger


CONTINUITY_DETECTION_PROMPT = """You are analyzing if a user's follow-up query continues a previous action.

## Previous Action
Type: {action_type}
Intent: {intent}
SQL Generated: {sql}
Result Summary: {result_summary}
Parameters: {parameters}

## Current Query
{current_query}

## Task
Determine if the current query is:
1. A continuation of the previous action (implicit follow-up)
2. A completely new query

## Classification Rules
- "continuation" if: User is modifying parameters, asking for visualizations of previous results, refining previous query
- "new_query" if: User is asking about a different topic, metric, or table

## Response Format (JSON)
{{
  "is_continuation": true/false,
  "continuation_type": "parameter_change" | "visualization_request" | "refinement" | "new_query",
  "inherited_action": {{
    "action_type": "sql_query" | "rag_query" | "mixed_query",
    "base_sql": "the SQL to re-run or modify",
    "base_parameters": {{}},
    "needs_rerun": true/false
  }},
  "parameter_changes": {{
    "addiction_level": "Medium",
    "visualization_type": "bar_chart"
  }},
  "reasoning": "Brief explanation"
}}

## Examples

Example 1:
Previous: "Vẽ biểu đồ cho High addiction level"
Current: "Đổi sang Medium"
Response: {{"is_continuation": true, "continuation_type": "parameter_change", "inherited_action": {{"action_type": "sql_query", "base_sql": "SELECT...", "needs_rerun": true}}, "parameter_changes": {{"addiction_level": "Medium"}}}}

Example 2:
Previous: "Calculate average study_hours by addiction_level"
Current: "Vẽ biểu đồ cho kết quả vừa rồi"
Response: {{"is_continuation": true, "continuation_type": "visualization_request", "inherited_action": {{"action_type": "sql_query", "base_sql": "SELECT...", "needs_rerun": true, "add_visualization": true}}}}

Example 3:
Previous: "Calculate DAU for last 7 days"
Current: "What is retention D1?"
Response: {{"is_continuation": false, "continuation_type": "new_query"}}

Now analyze the given query and respond with JSON only."""


def detect_implicit_continuation(
    current_query: str,
    last_action: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Use LLM to detect if current query is an implicit continuation.

    Args:
        current_query: The user's current question
        last_action: Previous action with SQL, parameters, etc.

    Returns:
        {
            "is_continuation": bool,
            "continuation_type": str,
            "inherited_action": dict,
            "parameter_changes": dict,
            "reasoning": str,
        }
    """
    if not last_action:
        return {
            "is_continuation": False,
            "continuation_type": "new_query",
            "inherited_action": {},
            "parameter_changes": {},
            "reasoning": "No previous action to continue from",
        }

    # Build context for LLM
    action_type = last_action.get("action_type", "unknown")
    intent = last_action.get("intent", "unknown")
    sql = last_action.get("generated_sql", "")
    result_summary = last_action.get("result_summary", {})
    parameters = last_action.get("parameters", {})

    prompt = CONTINUITY_DETECTION_PROMPT.format(
        action_type=action_type,
        intent=intent,
        sql=sql[:500] if sql else "N/A",
        result_summary=json.dumps(result_summary, ensure_ascii=False)[:300]
        if result_summary
        else "N/A",
        parameters=json.dumps(parameters, ensure_ascii=False) if parameters else "{}",
        current_query=current_query,
    )

    try:
        settings = load_settings()
        client = LLMClient.from_env()

        response = client.chat_completion(
            messages=[
                {"role": "user", "content": prompt},
            ],
            model=settings.model_fallback,  # Use fast/cheap model
            temperature=0.0,
            response_format={"type": "json_object"},
        )

        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")

        if not content:
            logger.warning("Empty response from continuity detection LLM")
            return _fallback_detection(current_query, last_action)

        # Parse JSON response
        result = _parse_json_response(content)

        if result:
            logger.info(
                "Continuity detection: is_continuation={is_cont}, type={type}",
                is_cont=result.get("is_continuation", False),
                type=result.get("continuation_type", "unknown"),
            )
            return result
        else:
            return _fallback_detection(current_query, last_action)

    except Exception as exc:
        logger.warning(
            "Continuity detection LLM failed: {error}, using fallback",
            error=str(exc),
        )
        return _fallback_detection(current_query, last_action)


def _parse_json_response(content: str) -> dict[str, Any] | None:
    """Parse JSON from LLM response."""
    try:
        # Try direct parse
        return json.loads(content)
    except json.JSONDecodeError:
        # Try to extract JSON from response
        import re

        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                return None
        return None


def _fallback_detection(
    current_query: str, last_action: dict[str, Any]
) -> dict[str, Any]:
    """
    Fallback detection using simple heuristics when LLM fails.

    Uses keyword matching for common continuation patterns.
    """
    query_lower = current_query.lower()

    # Keywords indicating continuation
    continuation_keywords = [
        "còn",
        "thì sao",
        "còn nữa",
        "đổi sang",
        "thay bằng",
        "với",
        "bây giờ",
        "now",
        "change to",
        "switch to",
        "what about",
        "and",
        "also",
    ]

    # Check for visualization request
    viz_keywords = ["vẽ", "biểu đồ", "chart", "graph", "visualize", "plot"]
    is_viz_request = any(kw in query_lower for kw in viz_keywords)

    # Check for "resultfrom previous" phrases
    result_keywords = [
        "kết quả vừa rồi",
        "previous result",
        "刚才的结果",
        "result above",
    ]
    is_result_request = any(kw in query_lower for kw in result_keywords)

    # Check for continuation
    is_continuation = any(kw in query_lower for kw in continuation_keywords)

    if is_viz_request and is_result_request:
        return {
            "is_continuation": True,
            "continuation_type": "visualization_request",
            "inherited_action": {
                "action_type": last_action.get("action_type", "sql_query"),
                "base_sql": last_action.get("generated_sql", ""),
                "needs_rerun": True,
                "add_visualization": True,
            },
            "parameter_changes": {},
            "reasoning": "Fallback: Visualization of previous result detected",
        }

    if is_continuation:
        return {
            "is_continuation": True,
            "continuation_type": "parameter_change",
            "inherited_action": {
                "action_type": last_action.get("action_type", "sql_query"),
                "base_sql": last_action.get("generated_sql", ""),
                "needs_rerun": True,
            },
            "parameter_changes": {},
            "reasoning": "Fallback: Continuation keywords detected",
        }

    return {
        "is_continuation": False,
        "continuation_type": "new_query",
        "inherited_action": {},
        "parameter_changes": {},
        "reasoning": "Fallback: No continuation detected",
    }


def extract_parameters_from_state(state: dict[str, Any]) -> dict[str, Any]:
    """
    Extract key parameters from AgentState for last_action storage.

    This captures what was done in the previous turn for continuity.
    """
    parameters = {}

    # Extract from user query
    user_query = state.get("user_query", "")
    parameters["original_query"] = user_query[:200]

    # Extract from generated SQL
    sql = state.get("generated_sql", "") or state.get("validated_sql", "")
    if sql:
        parameters["has_sql"] = True
        # Extract table names from SQL
        import re

        tables = re.findall(r"(?:FROM|JOIN)\s+(\w+)", sql, re.IGNORECASE)
        if tables:
            parameters["tables"] = list(set(tables))

    # Extract from context type
    context_type = state.get("context_type", "default")
    parameters["context_type"] = context_type

    # Extract from intent
    intent = state.get("intent", "unknown")
    parameters["intent"] = intent

    # Extract SQL result summary
    sql_result = state.get("sql_result", {})
    if sql_result:
        parameters["result_row_count"] = sql_result.get("row_count", 0)
        parameters["result_columns"] = list(sql_result.get("columns", []))[:10]

    return parameters


def summarize_result_for_context(sql_result: dict[str, Any]) -> dict[str, Any]:
    """
    Create a lightweight summary of SQL result for context.

    Does NOT include raw data - only metadata.
    """
    if not sql_result:
        return {}

    return {
        "row_count": sql_result.get("row_count", 0),
        "columns": list(sql_result.get("columns", []))[:10],
        "has_data": sql_result.get("row_count", 0) > 0,
    }
