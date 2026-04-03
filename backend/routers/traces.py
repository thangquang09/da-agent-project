"""Traces router for retrieving observability data.

Provides endpoints to fetch trace data for runs.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.logger import logger
from app.observability import read_traces_for_run

router = APIRouter(prefix="/traces", tags=["traces"])


@router.get("/{run_id}")
async def get_trace(run_id: str) -> dict[str, Any]:
    """
    Get full trace data for a specific run_id.

    Returns:
    - run_record: Run-level metadata (intent, status, latency, etc.)
    - node_records: List of node executions with timing and I/O summaries
    - tool_calls: Summary of tool invocations
    - execution_flow: Timeline of node executions
    """
    logger.info("backend.traces.get_trace run_id={run_id}", run_id=run_id)
    trace_data = read_traces_for_run(run_id)

    if not trace_data.get("found"):
        raise HTTPException(
            status_code=404, detail=f"Trace not found for run_id: {run_id}"
        )

    # Build execution flow timeline
    node_records = trace_data.get("node_records", [])
    execution_flow = []
    for node in node_records:
        execution_flow.append(
            {
                "node": node.get("node_name"),
                "attempt": node.get("attempt"),
                "status": node.get("status"),
                "latency_ms": node.get("latency_ms"),
                "started_at": node.get("started_at"),
                "observation_type": node.get("observation_type"),
                "error_category": node.get("error_category"),
            }
        )

    return {
        "run_id": run_id,
        "found": True,
        "run": trace_data.get("run_record"),
        "nodes": node_records,
        "execution_flow": execution_flow,
        "tool_calls": trace_data.get("tool_calls"),
        "stats": {
            "total_nodes": len(node_records),
            "error_nodes": sum(1 for n in node_records if n.get("status") == "error"),
            "total_latency_ms": trace_data.get("run_record", {}).get("latency_ms")
            if trace_data.get("run_record")
            else None,
        },
    }
