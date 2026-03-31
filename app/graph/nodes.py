from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from app.config import load_settings
from app.graph.state import AgentState, ContextType
from app.llm import LLMClient
from app.logger import logger
from app.memory.context_store import get_context_memory_store
from app.prompts import (
    ANALYSIS_PROMPT_DEFINITION,
    CONTEXT_DETECTION_PROMPT_DEFINITION,
    prompt_manager,
    ROUTER_PROMPT_DEFINITION,
    SQL_PROMPT_DEFINITION,
    SYNTHESIS_PROMPT_DEFINITION,
)
from app.tools import (
    dataset_context,
    get_schema_overview,
    query_sql,
    retrieve_business_context,
    retrieve_metric_definition,
    validate_sql,
)
from app.tools.mcp_client import call_mcp_tool


def _fallback_route_intent(query: str) -> str:
    return "unknown"


def _strip_diacritics(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn").replace(
        "đ", "d"
    )


def _fallback_context_type(
    user_semantic_context: str | None,
    uploaded_files: list[str] | None,
) -> tuple[ContextType, bool, str | None]:
    """
    Fallback context detection (rule-based, used when LLM fails).

    Returns:
        tuple of (context_type, needs_semantic_context, semantic_context)
    """
    uploaded_files = uploaded_files or []
    has_files = bool(uploaded_files)
    user_ctx = (user_semantic_context or "").strip()

    if user_ctx and has_files:
        return ("mixed", True, user_ctx)
    if user_ctx:
        return ("user_provided", True, user_ctx)
    if has_files:
        return ("csv_auto", True, None)

    return ("default", False, None)


def detect_context_type(state: AgentState) -> AgentState:
    """
    LLM-driven context type detection.

    Analyzes the query and any provided context to classify:
    - context_type: default | user_provided | csv_auto | mixed
    - needs_semantic_context: whether additional context would help

    Saves detection results to context_memory for long-term retention.
    """
    query = state.get("user_query", "")
    user_context = state.get("user_semantic_context", "") or ""
    uploaded_files = state.get("uploaded_files", []) or []
    run_id = state.get("run_id", "default")

    settings = load_settings()
    context_type: ContextType = "default"
    needs_semantic_context = False
    llm_usage: dict[str, int] | None = None
    llm_cost_usd: float | None = None
    detected_intent: list[str] = []

    try:
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=prompt_manager.context_detection_messages(
                query=query,
                user_semantic_context=user_context or None,
                uploaded_files=uploaded_files or None,
            ),
            model=settings.default_router_model,
            temperature=0.0,
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

        parsed = _extract_first_json_object(content)
        if parsed:
            ctx_type_raw = str(parsed.get("context_type", "")).strip().lower()
            if ctx_type_raw in {"default", "user_provided", "csv_auto", "mixed"}:
                context_type = ctx_type_raw
            needs_val = parsed.get("needs_semantic_context")
            if isinstance(needs_val, bool):
                needs_semantic_context = needs_val
            elif isinstance(needs_val, str):
                needs_semantic_context = needs_val.lower() in {"true", "1", "yes"}
        else:
            logger.warning(
                "Context detection LLM returned invalid JSON: {content}",
                content=content[:100],
            )
    except Exception as exc:
        logger.warning(
            "Context detection LLM failed, using fallback: {error}", error=str(exc)
        )
        context_type, needs_semantic_context, _ = _fallback_context_type(
            user_context, uploaded_files
        )

    try:
        context_store = get_context_memory_store()
        context_store.save_context(
            thread_id=run_id,
            run_id=run_id,
            context_type=context_type,
            needs_semantic_context=needs_semantic_context,
            detected_intent=detected_intent,
            query=query,
            user_provided_context=user_context or None,
            source_files=uploaded_files or None,
        )
    except Exception as exc:
        logger.warning("Failed to save context memory: {error}", error=str(exc))

    logger.info(
        "Context detection: type={context_type}, needs_context={needs_ctx}, "
        "has_files={has_files}, has_user_ctx={has_user}",
        context_type=context_type,
        needs_ctx=needs_semantic_context,
        has_files=bool(uploaded_files),
        has_user=bool(user_context),
    )

    update: AgentState = {
        "context_type": context_type,
        "needs_semantic_context": needs_semantic_context,
        "detected_intent": detected_intent,
        "tool_history": [
            {
                "tool": "detect_context_type",
                "status": "ok",
                "context_type": context_type,
                "needs_semantic_context": needs_semantic_context,
                "uploaded_files": uploaded_files,
                "token_usage": llm_usage,
                "cost_usd": llm_cost_usd,
            }
        ],
        "step_count": state.get("step_count", 0) + 1,
    }

    return update


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


def route_intent(state: AgentState) -> AgentState:
    query = state["user_query"]
    settings = load_settings()
    intent = "unknown"
    intent_reason = "llm_router"
    llm_usage: dict[str, int] | None = None
    llm_cost_usd: float | None = None

    try:
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=prompt_manager.router_messages(query),
            model=settings.default_router_model,
            temperature=0.0,
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
        parsed = _extract_first_json_object(content)
        candidate = str((parsed or {}).get("intent", "")).strip().lower()
        reason = str((parsed or {}).get("reason", "")).strip()
        if candidate in {"sql", "rag", "mixed", "unknown"}:
            intent = candidate
            intent_reason = reason or "llm_router"
        else:
            logger.warning(
                "Router LLM returned invalid intent: {candidate}", candidate=candidate
            )
            intent_reason = "llm_invalid_output"
    except Exception as exc:  # noqa: BLE001
        logger.error("Router LLM failed: {error}", error=str(exc))
        intent_reason = f"llm_error:{type(exc).__name__}"

    logger.info("Routed intent={intent} for query={query}", intent=intent, query=query)
    return {
        "intent": intent,
        "intent_reason": intent_reason,
        "tool_history": [
            {
                "tool": "route_intent",
                "status": "ok",
                "intent": intent,
                "reason": intent_reason,
                "prompt_name": ROUTER_PROMPT_DEFINITION.name,
                "token_usage": llm_usage,
                "cost_usd": llm_cost_usd,
            }
        ],
        "step_count": state.get("step_count", 0) + 1,
    }


def retrieve_dataset_context(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    """
    Retrieve relevant dataset context chunks from RAG index.
    For Phase 1: Uses existing RAG retriever with dataset_contexts filter.
    """
    from app.rag.retriever import query_index as _query_index

    results = _query_index(query=query, top_k=top_k, source_filter="dataset_contexts")
    return results


def get_schema(state: AgentState) -> AgentState:
    settings = load_settings()
    db_path = Path(state["target_db_path"]) if state.get("target_db_path") else None
    context_type = state.get("context_type", "default")

    if settings.enable_mcp_tool_client:
        mcp_args = {"db_path": str(db_path)} if db_path else {}
        overview = call_mcp_tool("get_schema", mcp_args)
        dataset_ctx = call_mcp_tool("dataset_context", mcp_args)
        source = "mcp"
    else:
        overview = get_schema_overview(db_path=db_path)
        dataset_ctx = dataset_context(db_path=db_path)
        source = "local"

    schema_context = json.dumps(overview, ensure_ascii=False)

    update: AgentState = {
        "schema_context": schema_context,
        "dataset_context": json.dumps(dataset_ctx, ensure_ascii=False),
        "tool_history": [
            {
                "tool": "get_schema",
                "status": "ok",
                "table_count": len(overview.get("tables", [])),
                "db_path": str(db_path) if db_path else "default",
                "source": source,
                "context_type": context_type,
            }
        ],
        "step_count": state.get("step_count", 0) + 1,
    }

    if context_type in ("user_provided", "csv_auto", "mixed"):
        try:
            query = state["user_query"]
            retrieved = retrieve_dataset_context(query=query, top_k=3)
            update["retrieved_dataset_context"] = retrieved
            logger.info(
                "Retrieved {count} dataset context chunks for context_type={context_type}",
                count=len(retrieved),
                context_type=context_type,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to retrieve dataset context: {error}", error=str(exc)
            )
            update["retrieved_dataset_context"] = []

    return update


def _llm_decide_retrieval_type(query: str) -> str:
    """
    Use LLM to decide whether to retrieve metric definition or business context.
    Returns 'metric_definition' or 'business_context'.
    """
    system_prompt = """You are a query classifier for a data analyst agent.
Given a user query, decide whether it asks for:
1. 'metric_definition' - if the user is asking for the definition, formula, or meaning of a metric/KPI (e.g., "What is DAU?", "Retention D1 là gì?", "How is revenue calculated?")
2. 'business_context' - if the user is asking for business rules, caveats, data quality notes, or general business context (e.g., "What caveats apply?", "Any data quality notes?", "Business rules for this metric?")

Respond with ONLY a JSON object: {"retrieval_type": "metric_definition" or "business_context", "reason": "brief reason"}"""

    try:
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ],
            model="gh/gpt-4o-mini",
            temperature=0.0,
            stream=False,
        )
        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        parsed = _extract_first_json_object(content)
        if parsed and "retrieval_type" in parsed:
            retrieval_type = str(parsed["retrieval_type"]).strip().lower()
            if retrieval_type in ("metric_definition", "business_context"):
                return retrieval_type
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM retrieval type decision failed: {error}", error=str(exc))
    return "business_context"


def retrieve_context_node(state: AgentState) -> AgentState:
    query = state["user_query"]
    intent = state.get("intent", "unknown")
    settings = load_settings()

    try:
        retrieval_type = _llm_decide_retrieval_type(query)
        tool_name = f"retrieve_{retrieval_type}"

        if retrieval_type == "metric_definition":
            if settings.enable_mcp_tool_client:
                result = call_mcp_tool(
                    "retrieve_metric_definition", {"query": query, "top_k": 4}
                )
            else:
                result = retrieve_metric_definition(query=query, top_k=4)
        else:
            result = retrieve_business_context(query=query, top_k=4)

        return {
            "retrieved_context": result["results"],
            "tool_history": [
                {
                    "tool": tool_name,
                    "status": "ok",
                    "result_count": result["result_count"],
                    "retrieval_type": retrieval_type,
                }
            ],
            "step_count": state.get("step_count", 0) + 1,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "errors": [
                {
                    "category": "RAG_RETRIEVAL_ERROR",
                    "message": str(exc),
                }
            ],
            "tool_history": [
                {
                    "tool": "retrieve_context",
                    "status": "failed",
                    "error": str(exc),
                }
            ],
            "step_count": state.get("step_count", 0) + 1,
        }


def _extract_sql_from_content(content: str) -> str:
    text = content.strip()
    if not text:
        return ""

    # Prefer fenced SQL blocks when the model returns markdown.
    fenced_matches = re.findall(
        r"```(?:sql)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL
    )
    for candidate in fenced_matches:
        cleaned = candidate.strip()
        if cleaned:
            return cleaned

    # Fallback: keep only from first SELECT/WITH statement onward.
    statement_match = re.search(r"\b(SELECT|WITH)\b[\s\S]*", text, flags=re.IGNORECASE)
    if statement_match:
        return statement_match.group(0).strip()

    return text


def _build_semantic_context(state: AgentState) -> str:
    """
    Build semantic context string from user provided context and RAG retrieved chunks.
    """
    parts: list[str] = []

    user_context = state.get("user_semantic_context", "")
    if user_context:
        parts.append(f"[User provided]: {user_context}")

    retrieved = state.get("retrieved_dataset_context", [])
    if retrieved:
        chunks = []
        for item in retrieved[:3]:
            source = item.get("source", "unknown")
            text = item.get("text", "")[:200]
            chunks.append(f"- [{source}] {text}")
        if chunks:
            parts.append("[Relevant context]:\n" + "\n".join(chunks))

    return "\n\n".join(parts) if parts else ""


def generate_sql(state: AgentState) -> AgentState:
    query = state["user_query"]
    settings = load_settings()
    sql = ""
    llm_usage: dict[str, int] | None = None
    llm_cost_usd: float | None = None
    semantic_context = _build_semantic_context(state)
    generation_status = "skipped"

    try:
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=prompt_manager.sql_messages(
                query,
                state.get("schema_context", ""),
                state.get("dataset_context", ""),
                semantic_context,
            ),
            model=settings.default_router_model,
            temperature=0.0,
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
            extracted_sql = _extract_sql_from_content(content)
            if extracted_sql:
                sql = extracted_sql
                generation_status = "llm_generated"
        if not sql:
            generation_status = "llm_empty_output"
    except Exception as exc:  # noqa: BLE001
        logger.error("LLM SQL generation failed: {error}", error=str(exc))
        generation_status = f"llm_error:{type(exc).__name__}"

    return {
        "generated_sql": sql,
        "tool_history": [
            {
                "tool": "generate_sql",
                "status": generation_status,
                "prompt_name": SQL_PROMPT_DEFINITION.name,
                "token_usage": llm_usage,
                "cost_usd": llm_cost_usd,
                "has_semantic_context": bool(semantic_context),
            }
        ],
        "step_count": state.get("step_count", 0) + 1,
    }


def validate_sql_node(state: AgentState) -> AgentState:
    db_path = Path(state["target_db_path"]) if state.get("target_db_path") else None
    result = validate_sql(
        state.get("generated_sql", ""), db_path=db_path, max_limit=200
    )
    update: AgentState = {
        "validated_sql": result.sanitized_sql,
        "tool_history": [
            {
                "tool": "validate_sql",
                "status": "ok" if result.is_valid else "failed",
                "reasons": result.reasons,
                "db_path": str(db_path) if db_path else "default",
            }
        ],
        "step_count": state.get("step_count", 0) + 1,
    }
    if not result.is_valid:
        update["errors"] = [
            {
                "category": "SQL_VALIDATION_ERROR",
                "message": "; ".join(result.reasons),
            }
        ]
    return update


def execute_sql_node(state: AgentState) -> AgentState:
    validated_sql = state.get("validated_sql", "")
    db_path = Path(state["target_db_path"]) if state.get("target_db_path") else None
    settings = load_settings()

    if settings.enable_mcp_tool_client:
        mcp_args: dict[str, Any] = {"sql": validated_sql, "row_limit": 200}
        if db_path:
            mcp_args["db_path"] = str(db_path)
        result = call_mcp_tool("query_sql", mcp_args)
        source = "mcp"
    else:
        result = query_sql(validated_sql, db_path=db_path)
        source = "local"

    row_count = int(result.get("row_count", 0)) if isinstance(result, dict) else 0
    validation_reasons = (
        result.get("validation_reasons") if isinstance(result, dict) else None
    )
    rejected_by_validator = bool(validation_reasons)

    update: AgentState = {
        "sql_result": result,
        "tool_history": [
            {
                "tool": "query_sql",
                "status": "failed" if rejected_by_validator else "ok",
                "row_count": row_count,
                "db_path": str(db_path) if db_path else "default",
                "source": source,
                **(
                    {"validation_reasons": validation_reasons}
                    if rejected_by_validator
                    else {}
                ),
            }
        ],
        "step_count": state.get("step_count", 0) + 1,
    }

    if rejected_by_validator:
        update["errors"] = [
            {
                "category": "SQL_VALIDATION_ERROR",
                "message": "; ".join(validation_reasons),
            }
        ]

    return update


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


def analyze_result(state: AgentState) -> AgentState:
    sql_result = state.get("sql_result", {})
    rows = sql_result.get("rows", [])
    query = state.get("user_query", "")
    validated_sql = state.get("validated_sql", state.get("generated_sql", ""))
    expected_keywords = state.get("expected_keywords", [])
    settings = load_settings()
    llm_usage: dict[str, int] | None = None
    llm_cost_usd: float | None = None

    if not rows:
        analysis: dict[str, Any] = {"summary": "No rows returned.", "trend": "unknown"}
    else:
        # Generate meaningful summary from actual data as fallback
        data_summary = _generate_data_summary(rows, query)
        analysis = {"summary": data_summary, "trend": "analyzed"}

        try:
            client = LLMClient.from_env()
            response = client.chat_completion(
                messages=prompt_manager.analysis_messages(
                    query=query,
                    sql=validated_sql,
                    results=rows,
                    expected_keywords=expected_keywords if expected_keywords else None,
                ),
                model=settings.default_router_model,
                temperature=0.0,
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
                parsed = _extract_first_json_object(content)
                if parsed and isinstance(parsed, dict):
                    llm_summary = parsed.get("summary", "")
                    # Only use LLM summary if it's meaningful (not generic)
                    if llm_summary and llm_summary.lower() not in [
                        "query executed successfully.",
                        "success",
                        "completed",
                    ]:
                        analysis = {
                            "summary": llm_summary,
                            "trend": parsed.get("trend", "analyzed"),
                            "insights": parsed.get("insights", []),
                        }
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LLM analysis failed, using data summary: {error}", error=str(exc)
            )

    return {
        "analysis_result": analysis,
        "tool_history": [
            {
                "tool": "analyze_result",
                "status": "ok",
                "prompt_name": ANALYSIS_PROMPT_DEFINITION.name,
                "token_usage": llm_usage,
                "cost_usd": llm_cost_usd,
            }
        ],
        "step_count": state.get("step_count", 0) + 1,
    }


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


def _unsupported_numeric_claims(answer: str, evidence: list[str]) -> list[str]:
    answer_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", answer))
    evidence_text = " ".join(evidence)
    evidence_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", evidence_text))
    return [
        f"numeric_claim:{number}"
        for number in sorted(answer_numbers)
        if number not in evidence_numbers
    ]


def _generate_natural_response(
    query: str, sql_rows: list[dict[str, Any]], row_count: int
) -> tuple[str, dict[str, int] | None, float | None]:
    """Use LLM to generate a natural language response from SQL results."""
    if not sql_rows:
        return "Không có dữ liệu nào được tìm thấy.", None, None

    settings = load_settings()
    llm_usage: dict[str, int] | None = None
    llm_cost_usd: float | None = None

    try:
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=prompt_manager.synthesis_messages(
                query=query,
                results=sql_rows,
                row_count=row_count,
            ),
            model=settings.default_router_model,
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


def synthesize_answer(state: AgentState) -> AgentState:
    intent = state.get("intent", "unknown")
    errors = state.get("errors", [])
    sql_rows = state.get("sql_result", {}).get("rows", [])
    analysis = state.get("analysis_result", {})
    retrieved_context = state.get("retrieved_context", [])
    context_evidence = _context_evidence(retrieved_context)
    tool_history = state.get("tool_history", [])

    total_token_usage = 0
    total_cost_usd = 0.0
    synthesis_usage: dict[str, int] | None = None
    synthesis_cost: float | None = None

    for item in tool_history:
        usage = item.get("token_usage", {}) if isinstance(item, dict) else {}
        if isinstance(usage, dict):
            total_token_usage += int(usage.get("total_tokens", 0) or 0)
        if isinstance(item, dict):
            total_cost_usd += float(item.get("cost_usd", 0) or 0)

    confidence = "low"
    if intent == "sql":
        if errors:
            error_msg = errors[-1]["message"]
            answer = f"Cannot answer safely because SQL validation failed: {error_msg}"
            confidence = "low"
        else:
            # Generate natural language response using LLM
            row_count = state.get("sql_result", {}).get("row_count", 0)
            natural_answer, syn_usage, syn_cost = _generate_natural_response(
                state.get("user_query", ""),
                sql_rows,
                row_count,
            )
            answer = natural_answer
            synthesis_usage = syn_usage
            synthesis_cost = syn_cost
            if syn_usage:
                total_token_usage += int(syn_usage.get("total_tokens", 0) or 0)
            if syn_cost:
                total_cost_usd += syn_cost
            confidence = "high" if sql_rows else "medium"
    elif intent == "rag":
        if retrieved_context:
            answer = (
                "From business docs, here is the most relevant context:\n"
                + "\n".join(f"- {item}" for item in context_evidence)
            )
            confidence = "medium"
        else:
            answer = "I could not retrieve relevant business documentation for this question."
            confidence = "low"
    elif intent == "mixed":
        has_sql_validation_error = any(
            err.get("category") == "SQL_VALIDATION_ERROR" for err in errors
        )
        sql_executed = "sql_result" in state and isinstance(
            state.get("sql_result"), dict
        )
        has_sql = sql_executed and not has_sql_validation_error
        has_context = bool(retrieved_context)

        # Generate natural language for SQL part if available
        sql_natural = None
        if has_sql:
            row_count = state.get("sql_result", {}).get("row_count", 0)
            sql_natural, syn_usage, syn_cost = _generate_natural_response(
                state.get("user_query", ""),
                sql_rows,
                row_count,
            )
            if syn_usage:
                total_token_usage += int(syn_usage.get("total_tokens", 0) or 0)
            if syn_cost:
                total_cost_usd += syn_cost

        if has_sql and has_context:
            answer = f"{sql_natural}\n\n**Context bổ sung:**\n" + "\n".join(
                f"- {item}" for item in context_evidence
            )
            confidence = "high"
        elif has_sql:
            answer = sql_natural or analysis.get(
                "summary", "SQL executed successfully."
            )
            confidence = "medium"
        elif has_context:
            answer = "Dựa trên tài liệu nghiệp vụ:\n" + "\n".join(
                f"- {item}" for item in context_evidence
            )
            confidence = "medium"
        else:
            answer = "I could not complete either SQL or retrieval branch for this mixed question."
            confidence = "low"
    else:
        answer = _llm_synthesize_fallback(
            query=state.get("user_query", ""),
            intent=intent,
            errors=errors,
        )
        confidence = "medium"

    evidence = [
        f"intent={intent}",
        f"rows={state.get('sql_result', {}).get('row_count', 0)}",
        f"context_chunks={len(retrieved_context)}",
    ]
    if analysis.get("summary"):
        evidence.append(f"analysis_summary={analysis['summary']}")

    unsupported_claims = _unsupported_numeric_claims(answer, evidence)
    if unsupported_claims:
        answer = answer + "\n\n[UNSUPPORTED_CLAIMS] " + ", ".join(unsupported_claims)

    # Include SQL result rows in payload for raw display
    sql_rows = state.get("sql_result", {}).get("rows", [])
    sql_row_count = state.get("sql_result", {}).get("row_count", 0)

    payload = {
        "answer": answer,
        "evidence": evidence,
        "confidence": confidence,
        "used_tools": [item["tool"] for item in tool_history],
        "generated_sql": state.get("validated_sql", state.get("generated_sql", "")),
        "error_categories": [str(err.get("category", "UNKNOWN")) for err in errors],
        "step_count": state.get("step_count", 0) + 1,
        "total_token_usage": total_token_usage,
        "total_cost_usd": round(total_cost_usd, 8),
        "unsupported_claims": unsupported_claims,
        "context_type": state.get("context_type", "default"),
        "sql_rows": sql_rows,
        "sql_row_count": sql_row_count,
    }
    return {
        "final_answer": answer,
        "final_payload": payload,
        "intent": intent,
        "intent_reason": state.get("intent_reason", ""),
        "errors": errors,
        "confidence": confidence,
        "step_count": state.get("step_count", 0) + 1,
    }


def _llm_synthesize_fallback(
    query: str, intent: str, errors: list[dict[str, Any]]
) -> str:
    """
    Use LLM to synthesize a helpful response when intent is unknown or routing failed.
    """
    system_prompt = """You are a helpful data analyst assistant. A user query could not be classified into SQL/RAG/Mixed intent.

If the query asks about data analysis, metrics, KPIs, trends, or business definitions, politely explain what types of questions you can answer and suggest example questions.

If the query is a greeting or conversational, respond friendly and briefly.

Always be helpful and concise. Respond in the same language as the user's query."""

    user_prompt = f"Query: {query}\nPredicted intent: {intent}\nErrors: {errors}\n\nProvide a helpful response."

    try:
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model="gh/gpt-4o-mini",
            temperature=0.7,
            stream=False,
        )
        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if content:
            return content
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM fallback synthesis failed: {error}", error=str(exc))

    return "I can help with data analysis questions about metrics, trends, and business definitions. Please ask about DAU, revenue, retention, or other KPIs."


def process_uploaded_files(state: AgentState) -> AgentState:
    """
    Process uploaded CSV files: validate, profile, and auto-register into database.

    This node runs after context detection and before routing when files are present.
    For each uploaded CSV:
    1. Validate file (size, encoding, delimiter)
    2. Profile data (schema, stats)
    3. Auto-register as table in SQLite database
    """
    from pathlib import Path
    from tempfile import NamedTemporaryFile

    from app.tools.auto_register import auto_register_csv

    uploaded_file_data = state.get("uploaded_file_data", [])
    if not uploaded_file_data:
        logger.info("No uploaded files to process")
        return {
            "registered_tables": [],
            "step_count": state.get("step_count", 0) + 1,
            "tool_history": [
                {
                    "tool": "process_uploaded_files",
                    "status": "skipped",
                    "reason": "no_files",
                }
            ],
        }

    db_path = state.get("target_db_path") or str(
        Path(__file__).parent.parent.parent / "data" / "warehouse" / "analytics.db"
    )
    registered_tables: list[str] = []
    tool_history_entries: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for file_info in uploaded_file_data:
        filename = file_info.get("name", "unknown.csv")
        file_bytes = file_info.get("data")
        if not file_bytes:
            errors.append(
                {
                    "category": "CSV_PROCESSING_ERROR",
                    "message": f"No data for file: {filename}",
                    "file": filename,
                }
            )
            continue

        try:
            with NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name

            result, error = auto_register_csv(
                file_path=tmp_path,
                db_path=db_path,
                table_name=Path(filename).stem,
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
        "errors": errors,
        "step_count": state.get("step_count", 0) + 1,
        "tool_history": tool_history_entries,
    }
