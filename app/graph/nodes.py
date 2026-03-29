from __future__ import annotations

import json
import re
import unicodedata
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
        "la gi",
        "dinh nghia",
        "quy tac",
        "business rule",
    }
    sql_keywords = {
        "top",
        "trend",
        "compare",
        "bao nhieu",
        "tang",
        "giam",
        "7 ngay",
        "week",
        "doanh thu",
        "dau",
    }

    has_rag = any(word in q_ascii for word in rag_keywords)
    has_sql = any(word in q_ascii for word in sql_keywords)
    if has_rag and has_sql:
        return "mixed"
    if has_rag:
        return "rag"
    return "sql"


def _strip_diacritics(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn").replace("Ä‘", "d")



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
            }
        ],
        "step_count": state.get("step_count", 0) + 1,
    }


def get_schema(state: AgentState) -> AgentState:
    overview = get_schema_overview()
    schema_context = json.dumps(overview, ensure_ascii=False)
    return {
        "schema_context": schema_context,
        "tool_history": [{"tool": "get_schema", "status": "ok", "table_count": len(overview.get("tables", []))}],
        "step_count": state.get("step_count", 0) + 1,
    }


def retrieve_context_node(state: AgentState) -> AgentState:
    query = state["user_query"]
    intent = state.get("intent", "unknown")

    try:
        query_ascii = _strip_diacritics(query.lower())
        is_definition_like = any(
            keyword in query_ascii
            for keyword in {
                "la gi",
                "dinh nghia",
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
    q = query.lower()
    if "top" in q and "retention" in q:
        return "SELECT title, retention_rate FROM videos ORDER BY retention_rate DESC LIMIT 5"
    if "revenue" in q and ("7 ngay" in q or "7 day" in q):
        return "SELECT date, revenue FROM daily_metrics ORDER BY date DESC LIMIT 7"
    if "dau" in q:
        return "SELECT date, dau FROM daily_metrics ORDER BY date DESC LIMIT 7"
    return "SELECT date, dau, revenue FROM daily_metrics ORDER BY date DESC LIMIT 7"


def generate_sql(state: AgentState) -> AgentState:
    query = state["user_query"]
    settings = load_settings()
    sql = _rule_based_sql(query)

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
            if content:
                sql = content.split("```")[-1].strip() if "```" in content else content
        except Exception as exc:  # noqa: BLE001
            logger.warning("Falling back to rule-based SQL generation: {error}", error=str(exc))

    return {
        "generated_sql": sql,
        "tool_history": [{"tool": "generate_sql", "status": "ok", "prompt_version": SQL_GENERATION_PROMPT_V1.version}],
        "step_count": state.get("step_count", 0) + 1,
    }


def validate_sql_node(state: AgentState) -> AgentState:
    result = validate_sql(state.get("generated_sql", ""))
    update: AgentState = {
        "validated_sql": result.sanitized_sql,
        "tool_history": [
            {
                "tool": "validate_sql",
                "status": "ok" if result.is_valid else "failed",
                "reasons": result.reasons,
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
    result = query_sql(validated_sql)
    return {
        "sql_result": result,
        "tool_history": [{"tool": "query_sql", "status": "ok", "row_count": result["row_count"]}],
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
        "used_tools": [item["tool"] for item in state.get("tool_history", [])],
        "generated_sql": state.get("validated_sql", state.get("generated_sql", "")),
    }
    return {
        "final_answer": answer,
        "final_payload": payload,
        "confidence": confidence,
        "step_count": state.get("step_count", 0) + 1,
    }

