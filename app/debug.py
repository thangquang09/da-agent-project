from __future__ import annotations

import functools
from contextlib import contextmanager
from typing import Any

from app.logger import logger
from app.observability import get_current_tracer
from app.observability.tracer import _safe_jsonable


_FILTERED_KEYS = frozenset(
    {
        "xml_database_context",
        "schema_context",
        "session_context",
        "uploaded_file_data",
        "sql_result",
        "file_cache",
        "table_contexts",
        "retrieved_context",
        "messages",
        "visualization",
        "task_plan",
        "task_results",
        "tool_history",
        "aggregate_analysis",
        "report_sections",
        "report_draft",
        "report_final",
        "artifacts",  # v4: list of WorkerArtifact (can contain large image data)
    }
)


def _size_hint(value: Any) -> str:
    if value is None:
        return "<none>"
    if isinstance(value, str):
        return f"<str {len(value)} chars>"
    if isinstance(value, (list, tuple, set, frozenset)):
        return f"<{type(value).__name__} {len(value)} items>"
    if isinstance(value, dict):
        return f"<dict {len(value)} keys>"
    return f"<{type(value).__name__}>"


def _summarize_sql_result(value: Any) -> dict[str, Any] | str:
    if not isinstance(value, dict):
        return _size_hint(value)
    rows = value.get("rows")
    columns: list[Any] = []
    if isinstance(rows, list) and rows:
        first_row = rows[0]
        if isinstance(first_row, dict):
            columns = list(first_row.keys())[:20]
    return {
        "row_count": value.get("row_count"),
        "columns": columns,
    }


def _filtered_state(state: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in state.items():
        if key == "sql_result":
            out[key] = _summarize_sql_result(value)
        elif key in _FILTERED_KEYS:
            out[key] = _size_hint(value)
        else:
            out[key] = _safe_jsonable(value)
    return out


def trace_node(node_name: str | None = None):
    def decorator(fn):
        name = node_name or fn.__name__

        @functools.wraps(fn)
        def wrapper(state):
            tracer = get_current_tracer()
            run_id = "-"
            if isinstance(state, dict):
                run_id = str(
                    state.get("run_id")
                    or (tracer.run_id if tracer else "-")
                )
            elif tracer is not None:
                run_id = tracer.run_id
            task_id = "-"
            if isinstance(state, dict):
                task_id = str(
                    state.get("task_id")
                    or state.get("section_id")
                    or "-"
                )
            user_query = "-"
            if isinstance(state, dict):
                user_query = str(state.get("user_query", "-") or "-")
            node_logger = logger.bind(run_id=run_id, node_name=name, task_id=task_id, user_query=user_query)
            node_logger.debug("INPUT | {}", _filtered_state(state if isinstance(state, dict) else {}))

            try:
                result = fn(state)
                if isinstance(result, dict):
                    node_logger.debug("OUTPUT | {}", _filtered_state(result))
                else:
                    node_logger.debug("OUTPUT | <non-dict>")
                return result
            except Exception as exc:  # noqa: BLE001
                node_logger.error(
                    "ERROR | {}: {}",
                    type(exc).__name__,
                    str(exc)[:500],
                )
                raise

        return wrapper

    return decorator


@contextmanager
def bind_task_context(task_id: str, *, run_id: str | None = None, node_name: str | None = None, user_query: str | None = None):
    tracer = get_current_tracer()
    effective_run_id = run_id or (tracer.run_id if tracer else "-")
    effective_node_name = node_name or f"worker-{task_id}"
    effective_query = user_query or "-"
    with logger.contextualize(
        run_id=effective_run_id,
        node_name=effective_node_name,
        task_id=str(task_id),
        user_query=effective_query,
    ):
        yield logger.bind(
            run_id=effective_run_id,
            node_name=effective_node_name,
            task_id=str(task_id),
            user_query=effective_query,
        )
