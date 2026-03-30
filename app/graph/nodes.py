from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from app.config import load_settings
from app.graph.state import AgentState
from app.llm import LLMClient
from app.logger import logger
from app.prompts import ROUTER_PROMPT_V1, SQL_GENERATION_PROMPT_V1
from app.tools import (
    get_schema_overview,
    query_sql,
    retrieve_business_context,
    retrieve_metric_definition,
    validate_sql,
)


def _fallback_route_intent(query: str) -> str:
    q = query.lower()
    q_ascii = _strip_diacritics(q)
    rag_keywords = {
        "definition",
        "what is",
        "meaning",
        "caveat",
        "explain",
        "là gì",
        "định nghĩa",
        "quy tắc",
        "business rule",
    }
    sql_keywords = {
        "top",
        "trend",
        "compare",
        "bao nhiêu",
        "tăng",
        "giảm",
        "7 ngày",
        "week",
        "doanh thu",
        "dau",
    }

    has_rag = any(_strip_diacritics(word) in q_ascii for word in rag_keywords)
    has_sql = any(_strip_diacritics(word) in q_ascii for word in sql_keywords)
    if has_rag and has_sql:
        return "mixed"
    if has_rag:
        return "rag"
    return "sql"


def _strip_diacritics(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn").replace("đ", "d")



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
    intent = _fallback_route_intent(query)
    intent_reason = "fallback_keyword_router"
    llm_usage: dict[str, int] | None = None
    llm_cost_usd: float | None = None

    try:
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=[
                {"role": "system", "content": ROUTER_PROMPT_V1.system},
                {"role": "user", "content": ROUTER_PROMPT_V1.user_template.format(query=query)},
            ],
            model=settings.default_router_model,
            temperature=0.0,
            stream=False,
        )
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        llm_usage = response.get("_usage_normalized")
        llm_cost_usd = response.get("_cost_usd_estimate")
        parsed = _extract_first_json_object(content)
        candidate = str((parsed or {}).get("intent", "")).strip().lower()
        reason = str((parsed or {}).get("reason", "")).strip()
        if candidate in {"sql", "rag", "mixed"}:
            intent = candidate
            intent_reason = reason or "llm_router"
        else:
            logger.warning("Router LLM returned invalid intent. Using fallback.")
            intent_reason = "llm_invalid_output"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Router LLM failed, using fallback intent: {error}", error=str(exc))
        intent_reason = f"fallback_due_to_error:{type(exc).__name__}"

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
                "prompt_version": ROUTER_PROMPT_V1.version,
                "token_usage": llm_usage,
                "cost_usd": llm_cost_usd,
            }
        ],
        "step_count": state.get("step_count", 0) + 1,
    }


def get_schema(state: AgentState) -> AgentState:
    db_path = Path(state["target_db_path"]) if state.get("target_db_path") else None
    overview = get_schema_overview(db_path=db_path)
    schema_context = json.dumps(overview, ensure_ascii=False)
    return {
        "schema_context": schema_context,
        "tool_history": [
            {
                "tool": "get_schema",
                "status": "ok",
                "table_count": len(overview.get("tables", [])),
                "db_path": str(db_path) if db_path else "default",
            }
        ],
        "step_count": state.get("step_count", 0) + 1,
    }


def retrieve_context_node(state: AgentState) -> AgentState:
    query = state["user_query"]
    intent = state.get("intent", "unknown")

    try:
        query_ascii = _strip_diacritics(query.lower())
        is_definition_like = any(
            _strip_diacritics(keyword) in query_ascii
            for keyword in {
                "là gì",
                "định nghĩa",
                "definition",
                "what is",
                "meaning",
            }
        )

        if intent == "rag" and is_definition_like:
            result = retrieve_metric_definition(query=query, top_k=4)
            tool_name = "retrieve_metric_definition"
        else:
            result = retrieve_business_context(query=query, top_k=4)
            tool_name = "retrieve_business_context"

        return {
            "retrieved_context": result["results"],
            "tool_history": [
                {
                    "tool": tool_name,
                    "status": "ok",
                    "result_count": result["result_count"],
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


def _rule_based_sql(query: str) -> str:
    q = _strip_diacritics(query.lower())
    if "top" in q and "retention" in q:
        return "SELECT title, retention_rate FROM videos ORDER BY retention_rate DESC LIMIT 5"
    if "revenue" in q and (_strip_diacritics("7 ngày") in q or "7 day" in q):
        return "SELECT date, revenue FROM daily_metrics ORDER BY date DESC LIMIT 7"
    if "dau" in q:
        return "SELECT date, dau FROM daily_metrics ORDER BY date DESC LIMIT 7"
    return "SELECT date, dau, revenue FROM daily_metrics ORDER BY date DESC LIMIT 7"


def generate_sql(state: AgentState) -> AgentState:
    query = state["user_query"]
    settings = load_settings()
    sql = _rule_based_sql(query)
    llm_usage: dict[str, int] | None = None
    llm_cost_usd: float | None = None

    if settings.enable_llm_sql_generation:
        try:
            client = LLMClient.from_env()
            response = client.chat_completion(
                messages=[
                    {"role": "system", "content": SQL_GENERATION_PROMPT_V1.system},
                    {
                        "role": "user",
                        "content": SQL_GENERATION_PROMPT_V1.user_template.format(
                            query=query,
                            schema_context=state.get("schema_context", ""),
                        ),
                    },
                ],
                model=settings.default_router_model,
                temperature=0.0,
                stream=False,
            )
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            llm_usage = response.get("_usage_normalized")
            llm_cost_usd = response.get("_cost_usd_estimate")
            if content:
                sql = content.split("```")[-1].strip() if "```" in content else content
        except Exception as exc:  # noqa: BLE001
            logger.warning("Falling back to rule-based SQL generation: {error}", error=str(exc))

    return {
        "generated_sql": sql,
        "tool_history": [
            {
                "tool": "generate_sql",
                "status": "ok",
                "prompt_version": SQL_GENERATION_PROMPT_V1.version,
                "token_usage": llm_usage,
                "cost_usd": llm_cost_usd,
            }
        ],
        "step_count": state.get("step_count", 0) + 1,
    }


def validate_sql_node(state: AgentState) -> AgentState:
    db_path = Path(state["target_db_path"]) if state.get("target_db_path") else None
    result = validate_sql(state.get("generated_sql", ""), db_path=db_path)
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
    result = query_sql(validated_sql, db_path=db_path)
    return {
        "sql_result": result,
        "tool_history": [
            {
                "tool": "query_sql",
                "status": "ok",
                "row_count": result["row_count"],
                "db_path": str(db_path) if db_path else "default",
            }
        ],
        "step_count": state.get("step_count", 0) + 1,
    }


def analyze_result(state: AgentState) -> AgentState:
    sql_result = state.get("sql_result", {})
    rows = sql_result.get("rows", [])
    analysis: dict[str, Any] = {"summary": "No rows returned.", "trend": "unknown"}

    if rows and "dau" in rows[0]:
        recent = rows[:2]
        if len(recent) == 2:
            trend = "up" if recent[0]["dau"] >= recent[1]["dau"] else "down"
            analysis = {
                "summary": f"Latest DAU={recent[0]['dau']} vs previous={recent[1]['dau']}",
                "trend": trend,
            }
    elif rows and "revenue" in rows[0]:
        values = [float(row["revenue"]) for row in rows]
        avg = sum(values) / len(values)
        analysis = {
            "summary": f"Average revenue over {len(values)} rows is {avg:.2f}",
            "trend": "computed_average",
        }
    elif rows and "retention_rate" in rows[0]:
        top = rows[0]
        analysis = {
            "summary": (
                f"Top retention video is '{top.get('title', 'unknown')}' "
                f"with retention_rate={float(top['retention_rate']):.2%}"
            ),
            "trend": "top_k",
        }

    return {
        "analysis_result": analysis,
        "tool_history": [{"tool": "analyze_result", "status": "ok"}],
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
            answer = analysis.get("summary", "Completed query execution.")
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
    else:  # mixed
        has_sql_validation_error = any(err.get("category") == "SQL_VALIDATION_ERROR" for err in errors)
        sql_executed = "sql_result" in state and isinstance(state.get("sql_result"), dict)
        has_sql = sql_executed and not has_sql_validation_error
        has_context = bool(retrieved_context)
        if has_sql and has_context:
            answer = (
                f"Data signal: {analysis.get('summary', 'SQL executed.')}\n"
                "Business context:\n"
                + "\n".join(f"- {item}" for item in context_evidence)
            )
            confidence = "high"
        elif has_sql:
            answer = (
                "Partial answer (SQL branch succeeded, retrieval branch missing): "
                f"{analysis.get('summary', 'SQL executed.')}"
            )
            confidence = "medium"
        elif has_context:
            answer = (
                "Partial answer (retrieval branch succeeded, SQL branch failed):\n"
                + "\n".join(f"- {item}" for item in context_evidence)
            )
            confidence = "medium"
        else:
            answer = "I could not complete either SQL or retrieval branch for this mixed question."
            confidence = "low"

    payload = {
        "answer": answer,
        "evidence": [
            f"intent={intent}",
            f"rows={state.get('sql_result', {}).get('row_count', 0)}",
            f"context_chunks={len(retrieved_context)}",
        ],
        "confidence": confidence,
        "used_tools": [item["tool"] for item in tool_history],
        "generated_sql": state.get("validated_sql", state.get("generated_sql", "")),
        "error_categories": [str(err.get("category", "UNKNOWN")) for err in errors],
        "step_count": state.get("step_count", 0) + 1,
        "total_token_usage": total_token_usage,
        "total_cost_usd": round(total_cost_usd, 8),
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

