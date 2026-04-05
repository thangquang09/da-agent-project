from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any

from app.graph import (
    build_sql_v3_graph,
    new_run_config,
    to_langgraph_config,
)
from app.logger import logger
from app.observability import RunTracer, reset_current_tracer, set_current_tracer


def _make_serializable(obj: Any) -> Any:
    """Convert bytes to base64-encoded str for JSON serialization."""
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode()
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_serializable(i) for i in obj]
    return obj

def _extract_numeric_evidence(payload: dict, key: str) -> int | None:
    for item in payload.get("evidence", []):
        text = str(item)
        if text.startswith(f"{key}="):
            try:
                return int(text.split("=", 1)[1])
            except ValueError:
                return None
    return None


def run_query(
    user_query: str,
    recursion_limit: int = 25,
    db_path: str | None = None,
    user_semantic_context: str | None = None,
    uploaded_files: list[str] | None = None,
    uploaded_file_data: list[dict[str, Any]] | None = None,
    expected_keywords: list[str] | None = None,
    version: str = "v3",
    thread_id: str | None = None,
) -> dict:
    if version != "v3":
        raise ValueError(f"Unsupported graph version: {version}")
    graph = build_sql_v3_graph()
    run_cfg = new_run_config(recursion_limit=recursion_limit, thread_id=thread_id)
    tracer = RunTracer(
        run_id=run_cfg.run_id,
        thread_id=run_cfg.thread_id,
        query=user_query,
    )
    tracer_token = set_current_tracer(tracer)
    graph_input: dict[str, Any] = {"user_query": user_query}
    graph_input["run_id"] = run_cfg.run_id
    if db_path:
        graph_input["target_db_path"] = str(Path(db_path))
    if user_semantic_context:
        graph_input["user_semantic_context"] = user_semantic_context
    if uploaded_files:
        graph_input["uploaded_files"] = uploaded_files
    if uploaded_file_data:
        graph_input["uploaded_file_data"] = uploaded_file_data
    if expected_keywords:
        graph_input["expected_keywords"] = expected_keywords
    # Pass thread_id to graph input for session memory
    if thread_id:
        graph_input["thread_id"] = thread_id
    try:
        output = graph.invoke(
            graph_input,
            config=to_langgraph_config(run_cfg),
        )
        payload = output.get("final_payload", {})
        payload["run_id"] = output.get("run_id", run_cfg.run_id)
        payload["intent"] = output.get("intent", payload.get("intent", "unknown"))
        payload["intent_reason"] = output.get("intent_reason", "")
        payload["response_mode"] = output.get(
            "response_mode", payload.get("response_mode", "answer")
        )
        payload["errors"] = output.get("errors", [])
        payload["step_count"] = output.get("step_count", payload.get("step_count"))
        payload["tool_history"] = output.get("tool_history", [])
        payload["rows"] = _extract_numeric_evidence(payload, "rows")
        payload["context_chunks"] = _extract_numeric_evidence(payload, "context_chunks")
        payload["error_categories"] = [
            str(item.get("category", "UNKNOWN")) for item in payload.get("errors", [])
        ]
        payload["context_type"] = output.get("context_type", "default")
        payload["thread_id"] = run_cfg.thread_id
        tracer.finish(payload=payload, status="success")
        return payload
    except Exception as exc:  # noqa: BLE001
        payload = {
            "run_id": run_cfg.run_id,
            "thread_id": run_cfg.thread_id,
            "answer": f"Run failed: {exc}",
            "evidence": ["intent=unknown", "rows=0", "context_chunks=0"],
            "confidence": "low",
            "used_tools": [],
            "generated_sql": "",
            "intent": "unknown",
            "intent_reason": "",
            "response_mode": "answer",
            "errors": [{"category": "SYNTHESIS_ERROR", "message": str(exc)}],
            "step_count": 0,
            "tool_history": [],
            "rows": 0,
            "context_chunks": 0,
            "error_categories": ["SYNTHESIS_ERROR"],
            "total_token_usage": None,
            "total_cost_usd": None,
            "context_type": "default",
        }
        tracer.finish(payload=payload, status="failed", error_message=str(exc))
        return payload
    finally:
        reset_current_tracer(tracer_token)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DA Agent SQL-first CLI")
    parser.add_argument("query", help="Business/data question")
    parser.add_argument(
        "--recursion-limit",
        type=int,
        default=25,
        help="LangGraph recursion limit safeguard",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Optional SQLite db path override for this run",
    )
    parser.add_argument(
        "--version",
        choices=["v3"],
        default="v3",
        help="Graph version to use",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_query(
        args.query,
        recursion_limit=args.recursion_limit,
        db_path=args.db_path,
        version=args.version,
    )
    logger.info(
        "Query completed with confidence={confidence}",
        confidence=result.get("confidence"),
    )
    # Convert bytes (e.g., PNG image_data) to base64 for JSON serialization
    serializable_result = _make_serializable(result)
    print(json.dumps(serializable_result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
