"""Task Grounder node — classifies user query into structured TaskProfile."""

from __future__ import annotations

import json
import re
from typing import Any

from app.config import load_settings
from app.graph.state import AgentState, TaskProfile
from app.llm.client import LLMClient
from app.logger import logger
from app.prompts.task_grounder import TASK_GROUNDER_PROMPT


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


def task_grounder(state: AgentState) -> AgentState:
    """Classify user query into a structured TaskProfile.

    Runs a single lightweight LLM call (gpt-4o-mini) to produce
    typed context for the supervisor instead of raw text guessing.

    Returns:
        AgentState with task_profile field set.
    """
    query = state.get("user_query", "")
    session_context = state.get("session_context", "")

    messages: list[dict[str, str]] = [
        {"role": "system", "content": TASK_GROUNDER_PROMPT.system_prompt},
    ]
    if session_context:
        messages.append(
            {
                "role": "user",
                "content": f"[Session Context]\n{session_context}\n\n[Câu hỏi hiện tại]\n{query}",
            }
        )
    else:
        messages.append({"role": "user", "content": query})

    try:
        client = LLMClient.from_env()
        settings = load_settings()
        response = client.chat_completion(
            messages=messages,
            model=settings.model_preclassifier,
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

        if parsed:
            task_profile: TaskProfile = {
                "task_mode": str(parsed.get("task_mode", "simple")),
                "data_source": str(parsed.get("data_source", "database")),
                "required_capabilities": parsed.get("required_capabilities", ["sql"]),
                "followup_mode": str(parsed.get("followup_mode", "fresh_query")),
                "confidence": str(parsed.get("confidence", "medium")),
                "reasoning": str(parsed.get("reasoning", "")),
            }
            logger.info(
                "Task grounder: mode={mode}, source={source}, caps={caps}, conf={conf}",
                mode=task_profile["task_mode"],
                source=task_profile["data_source"],
                caps=task_profile["required_capabilities"],
                conf=task_profile["confidence"],
            )
            return {
                "task_profile": task_profile,
                "tool_history": [
                    {
                        "tool": "task_grounder",
                        "status": "ok",
                        "task_profile": task_profile,
                    }
                ],
                "step_count": state.get("step_count", 0) + 1,
            }
        else:
            logger.warning(
                "Task grounder returned non-JSON: {content}", content=content[:200]
            )

    except Exception as exc:  # noqa: BLE001
        logger.warning("Task grounder failed: {error}", error=str(exc))
        return _fallback(state, str(exc))

    return _fallback(state, "unknown")


def _fallback(state: AgentState, reason: str) -> AgentState:
    """Return conservative fallback profile on error."""
    fallback_profile: TaskProfile = {
        "task_mode": "simple",
        "data_source": "database",
        "required_capabilities": ["sql"],
        "followup_mode": "fresh_query",
        "confidence": "low",
        "reasoning": f"Fallback due to: {reason}",
    }
    return {
        "task_profile": fallback_profile,
        "tool_history": [
            {
                "tool": "task_grounder",
                "status": "fallback",
                "reason": reason,
            }
        ],
        "step_count": state.get("step_count", 0) + 1,
    }
