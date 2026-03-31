from __future__ import annotations

from typing import Any

from app.graph.state import AgentState
from app.logger import logger


def resolve_context_conflicts(state: AgentState) -> AgentState:
    """
    Resolve conflicts between user-provided context and dataset context.

    When both user_semantic_context and retrieved_dataset_context exist:
    1. Prioritize schema/data truth over user hints
    2. Detect conflicts and log them
    3. Add conflict_notes to state for synthesis

    Returns:
        Updated AgentState with resolved_context and conflict_notes.
    """
    user_context = state.get("user_semantic_context", "") or ""
    retrieved_context = state.get("retrieved_dataset_context", []) or []

    if not user_context and not retrieved_context:
        return {
            "resolved_context": "",
            "conflict_notes": [],
        }

    if not user_context:
        resolved = _format_retrieved_context(retrieved_context)
        return {
            "resolved_context": resolved,
            "conflict_notes": [],
        }

    if not retrieved_context:
        return {
            "resolved_context": user_context,
            "conflict_notes": [],
        }

    conflicts = _detect_conflicts(user_context, retrieved_context)
    resolved = _prioritize_schema_truth(user_context, retrieved_context)

    if conflicts:
        logger.warning(
            "Context conflicts detected: {conflicts}",
            conflicts=conflicts,
        )

    return {
        "resolved_context": resolved,
        "conflict_notes": conflicts,
        "step_count": state.get("step_count", 0) + 1,
    }


def _format_retrieved_context(retrieved_context: list[dict[str, Any]]) -> str:
    """Format retrieved context chunks into a single string."""
    if not retrieved_context:
        return ""

    parts = []
    for chunk in retrieved_context[:5]:
        source = chunk.get("source", "unknown")
        text = chunk.get("text", "")[:300]
        parts.append(f"- [{source}] {text}")

    return "\n".join(parts)


def _detect_conflicts(
    user_context: str,
    retrieved_context: list[dict[str, Any]],
) -> list[str]:
    """
    Detect potential conflicts between user context and retrieved context.

    This is a lightweight heuristic check. Full conflict detection
    would require NLP analysis.
    """
    conflicts: list[str] = []
    user_lower = user_context.lower()

    for chunk in retrieved_context:
        text = chunk.get("text", "").lower()
        source = chunk.get("source", "unknown")
        _check_conflicts(user_lower, text, source, conflicts)

    return conflicts


def _check_conflicts(
    user_lower: str,
    text: str,
    source: str,
    conflicts: list[str],
) -> None:
    """Check for common conflict patterns between user context and retrieved text."""
    conflict_patterns = [
        ("revenue", "profit"),
        ("dau", "mau"),
        ("daily", "monthly"),
        ("total", "average"),
    ]

    for term_a, term_b in conflict_patterns:
        if term_a in user_lower and term_b in text and term_b not in user_lower:
            conflicts.append(
                f"User mentions '{term_a}' but {source} discusses '{term_b}'"
            )
        elif term_b in user_lower and term_a in text and term_a not in user_lower:
            conflicts.append(
                f"User mentions '{term_b}' but {source} discusses '{term_a}'"
            )


def _prioritize_schema_truth(
    user_context: str,
    retrieved_context: list[dict[str, Any]],
) -> str:
    """
    Build resolved context by combining user context and retrieved context.

    Prioritizes schema/data truth by placing retrieved context first,
    then appending user context with an explicit "User notes:" label.
    """
    retrieved_formatted = _format_retrieved_context(retrieved_context)

    if not retrieved_formatted:
        return user_context

    if not user_context.strip():
        return retrieved_formatted

    return f"{retrieved_formatted}\n\n[User notes]: {user_context}"
