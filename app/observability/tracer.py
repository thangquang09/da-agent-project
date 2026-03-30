from __future__ import annotations

import json
import os
import time
from collections import Counter
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import load_settings
from app.logger import logger
from app.observability.schemas import NodeTraceRecord, RunTraceRecord, utc_now_iso


_CURRENT_TRACER: ContextVar["RunTracer | None"] = ContextVar("run_tracer", default=None)

NODE_TO_FAILURE = {
    "route_intent": "ROUTING_ERROR",
    "generate_sql": "SQL_GENERATION_ERROR",
    "validate_sql_node": "SQL_VALIDATION_ERROR",
    "execute_sql_node": "SQL_EXECUTION_ERROR",
    "retrieve_context_node": "RAG_RETRIEVAL_ERROR",
    "synthesize_answer": "SYNTHESIS_ERROR",
}


@dataclass
class NodeScope:
    node_name: str
    attempt: int
    started_at: str
    started_perf: float
    input_summary: dict[str, Any]
    observation_type: str
    langfuse_observation: Any = None


def _safe_jsonable(value: Any, max_length: int = 300) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:max_length] + ("..." if len(value) > max_length else "")
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for idx, (k, v) in enumerate(value.items()):
            if idx >= 12:
                out["..."] = "truncated"
                break
            out[str(k)] = _safe_jsonable(v, max_length=max_length)
        return out
    if isinstance(value, list):
        compact = value[:8]
        return [_safe_jsonable(v, max_length=max_length) for v in compact] + (["..."] if len(value) > 8 else [])
    return str(value)[:max_length]


def _state_summary(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "intent": state.get("intent"),
        "step_count": state.get("step_count"),
        "has_schema_context": bool(state.get("schema_context")),
        "generated_sql": _safe_jsonable(state.get("generated_sql")),
        "validated_sql": _safe_jsonable(state.get("validated_sql")),
        "sql_row_count": state.get("sql_result", {}).get("row_count") if isinstance(state.get("sql_result"), dict) else None,
        "retrieved_context_count": len(state.get("retrieved_context", []) or []),
        "errors": _safe_jsonable(state.get("errors", [])),
    }


def _output_summary(update: dict[str, Any]) -> dict[str, Any]:
    return {
        "keys": sorted(list(update.keys())),
        "intent": update.get("intent"),
        "step_count": update.get("step_count"),
        "tool_history_delta": len(update.get("tool_history", []) or []),
        "errors_delta": _safe_jsonable(update.get("errors", [])),
        "generated_sql": _safe_jsonable(update.get("generated_sql")),
    }


class LangfuseAdapter:
    def __init__(self) -> None:
        self.enabled = False
        self.client = None
        self.root_observation = None

        settings = load_settings()
        if not settings.enable_langfuse:
            return
        required = ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"]
        if not all(os.getenv(key) for key in required):
            return

        try:
            # Langfuse doc suggests importing after env has been loaded.
            from langfuse import get_client  # type: ignore

            self.client = get_client()
            self.enabled = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Langfuse SDK not active: {error}", error=str(exc))
            self.enabled = False

    def start_run(self, run_id: str, query: str, thread_id: str) -> None:
        if not self.enabled or self.client is None:
            return
        try:
            self.root_observation = self.client.start_observation(
                name="da-agent-run",
                as_type="agent",
                input={"query": query, "run_id": run_id, "thread_id": thread_id},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Langfuse start_run failed: {error}", error=str(exc))

    def start_node(self, parent: Any, node_name: str, state: dict[str, Any], observation_type: str) -> Any:
        if not self.enabled or parent is None:
            return None
        try:
            return parent.start_observation(
                name=node_name,
                as_type=observation_type,
                input={"state": _state_summary(state)},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Langfuse start_node failed for {node}: {error}", node=node_name, error=str(exc))
            return None

    def end_node(self, node_obs: Any, update: dict[str, Any] | None, error_message: str | None) -> None:
        if not self.enabled or node_obs is None:
            return
        try:
            if update is not None:
                node_obs.update(output={"update": _output_summary(update)})
            if error_message:
                node_obs.update(level="ERROR", metadata={"error_message": error_message})
            node_obs.end()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Langfuse end_node failed: {error}", error=str(exc))

    def end_run(self, payload: dict[str, Any], status: str, error_message: str | None) -> None:
        if not self.enabled or self.root_observation is None:
            return
        try:
            self.root_observation.update(
                output={
                    "status": status,
                    "intent": payload.get("intent"),
                    "confidence": payload.get("confidence"),
                    "generated_sql": payload.get("generated_sql", ""),
                    "error_categories": payload.get("error_categories", []),
                }
            )
            if error_message:
                self.root_observation.update(level="ERROR", metadata={"error_message": error_message})
            self.root_observation.end()
            self.client.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Langfuse end_run failed: {error}", error=str(exc))


class RunTracer:
    def __init__(self, run_id: str, thread_id: str, query: str, trace_path: Path | None = None) -> None:
        self.run_id = run_id
        self.thread_id = thread_id
        self.query = query
        self.started_at = utc_now_iso()
        self.started_perf = time.perf_counter()
        settings = load_settings()
        self.trace_path = trace_path or Path(settings.trace_jsonl_path)
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        self.node_attempts: Counter[str] = Counter()
        self.node_records: list[NodeTraceRecord] = []
        self.langfuse = LangfuseAdapter()
        self.langfuse.start_run(run_id=run_id, query=query, thread_id=thread_id)

    def start_node(self, node_name: str, state: dict[str, Any], observation_type: str = "span") -> NodeScope:
        self.node_attempts[node_name] += 1
        attempt = self.node_attempts[node_name]
        scope = NodeScope(
            node_name=node_name,
            attempt=attempt,
            started_at=utc_now_iso(),
            started_perf=time.perf_counter(),
            input_summary=_state_summary(state),
            observation_type=observation_type,
            langfuse_observation=self.langfuse.start_node(
                parent=self.langfuse.root_observation,
                node_name=node_name,
                state=state,
                observation_type=observation_type,
            ),
        )
        return scope

    def end_node(self, scope: NodeScope, update: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        ended_at = utc_now_iso()
        latency_ms = round((time.perf_counter() - scope.started_perf) * 1000, 2)
        error_category = NODE_TO_FAILURE.get(scope.node_name, "SYNTHESIS_ERROR") if error else None
        error_message = str(error) if error else None
        output_summary = _output_summary(update or {})
        record = NodeTraceRecord(
            record_type="node",
            run_id=self.run_id,
            node_name=scope.node_name,
            attempt=scope.attempt,
            status="error" if error else "ok",
            started_at=scope.started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            input_summary=scope.input_summary,
            output_summary=output_summary,
            error_category=error_category,
            error_message=error_message,
            observation_type=scope.observation_type,
        )
        self.node_records.append(record)
        self._append_jsonl(record.to_dict())
        self.langfuse.end_node(scope.langfuse_observation, update=update, error_message=error_message)
        logger.info(
            "Trace node={node} attempt={attempt} status={status} latency_ms={latency}",
            node=scope.node_name,
            attempt=scope.attempt,
            status=record.status,
            latency=latency_ms,
        )

    def finish(self, payload: dict[str, Any], status: str = "success", error_message: str | None = None) -> None:
        ended_at = utc_now_iso()
        latency_ms = round((time.perf_counter() - self.started_perf) * 1000, 2)
        used_tools = [str(item) for item in payload.get("used_tools", [])]
        error_categories = [str(cat) for cat in payload.get("error_categories", [])]
        context_chunks = payload.get("context_chunks")
        if (
            payload.get("intent") in {"rag", "mixed"}
            and isinstance(context_chunks, int)
            and context_chunks == 0
            and "RAG_RETRIEVAL_ERROR" not in error_categories
        ):
            error_categories.append("RAG_IRRELEVANT_CONTEXT")

        row_count = payload.get("rows")
        if isinstance(row_count, int) and row_count == 0 and payload.get("intent") in {"sql", "mixed"}:
            error_categories.append("EMPTY_RESULT")
        if status == "failed" and "STEP_LIMIT_REACHED" not in error_categories and error_message and "recursion" in error_message.lower():
            error_categories.append("STEP_LIMIT_REACHED")

        fallback_used = any(
            "fallback" in str(item.get("reason", "")).lower()
            for item in payload.get("tool_history", [])
            if isinstance(item, dict)
        )
        retries = sum(max(0, count - 1) for count in self.node_attempts.values())

        run_record = RunTraceRecord(
            record_type="run",
            run_id=self.run_id,
            thread_id=self.thread_id,
            started_at=self.started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            query=self.query,
            routed_intent=str(payload.get("intent", "unknown")),
            status="failed" if status == "failed" else "success",
            total_steps=int(payload.get("step_count", 0) or 0),
            used_tools=used_tools,
            generated_sql=str(payload.get("generated_sql", "")),
            retry_count=retries,
            fallback_used=fallback_used,
            error_categories=sorted(set(error_categories)),
            total_token_usage=None,
            final_confidence=str(payload.get("confidence", "unknown")),
        )
        self._append_jsonl(run_record.to_dict())
        self.langfuse.end_run(payload=payload, status=status, error_message=error_message)
        logger.info(
            "Trace run_id={run_id} status={status} latency_ms={latency} intent={intent}",
            run_id=self.run_id,
            status=run_record.status,
            latency=latency_ms,
            intent=run_record.routed_intent,
        )

    def _append_jsonl(self, record: dict[str, Any]) -> None:
        with self.trace_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def set_current_tracer(tracer: RunTracer | None) -> Token:
    return _CURRENT_TRACER.set(tracer)


def reset_current_tracer(token: Token) -> None:
    _CURRENT_TRACER.reset(token)


def get_current_tracer() -> RunTracer | None:
    return _CURRENT_TRACER.get()
