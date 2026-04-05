"""Trace retrieval utilities for observability.

Provides functions to read and filter trace records from JSONL files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import load_settings


def read_traces_for_run(run_id: str, trace_path: Path | None = None) -> dict[str, Any]:
    """
    Read all trace records for a specific run_id from the JSONL trace file.

    Returns a structured dict with:
    - run_record: The run-level trace record
    - node_records: List of node-level trace records in execution order
    - tool_calls: Flattened list of tool calls from all nodes
    """
    settings = load_settings()
    trace_file = trace_path or Path(settings.trace_jsonl_path)

    run_record: dict[str, Any] | None = None
    node_records: list[dict[str, Any]] = []

    if not trace_file.exists():
        return {
            "run_id": run_id,
            "run_record": None,
            "node_records": [],
            "tool_calls": [],
            "found": False,
        }

    try:
        with trace_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    record_run_id = record.get("run_id")
                    if record_run_id != run_id:
                        continue

                    record_type = record.get("record_type")
                    if record_type == "run":
                        run_record = record
                    elif record_type == "node":
                        node_records.append(record)
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass

    # Sort node records by started_at time
    node_records.sort(key=lambda x: x.get("started_at", ""))

    # Extract tool calls from node records
    tool_calls: list[dict[str, Any]] = []
    for node in node_records:
        output = node.get("output_summary", {})
        if output.get("tool_history_delta", 0) > 0:
            tool_calls.append(
                {
                    "node": node.get("node_name"),
                    "tool_history_delta": output.get("tool_history_delta"),
                    "latency_ms": node.get("latency_ms"),
                    "status": node.get("status"),
                }
            )

    return {
        "run_id": run_id,
        "run_record": run_record,
        "node_records": node_records,
        "tool_calls": tool_calls,
        "found": run_record is not None or len(node_records) > 0,
    }


def get_latest_traces(
    limit: int = 10, trace_path: Path | None = None
) -> list[dict[str, Any]]:
    """
    Get the latest N run traces from the trace file.

    Returns a list of run records, sorted by started_at (newest first).
    """
    settings = load_settings()
    trace_file = trace_path or Path(settings.trace_jsonl_path)

    run_records: list[dict[str, Any]] = []

    if not trace_file.exists():
        return run_records

    try:
        with trace_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if record.get("record_type") == "run":
                        run_records.append(record)
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass

    # Sort by started_at (newest first) and limit
    run_records.sort(key=lambda x: x.get("started_at", ""), reverse=True)
    return run_records[:limit]
