from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RunConfig:
    thread_id: str
    run_id: str
    recursion_limit: int = 25


def new_run_config(thread_id: str | None = None, recursion_limit: int = 25) -> RunConfig:
    rid = str(uuid.uuid4())
    return RunConfig(
        thread_id=thread_id or rid,
        run_id=rid,
        recursion_limit=recursion_limit,
    )


def to_langgraph_config(run_config: RunConfig) -> dict[str, Any]:
    return {
        "configurable": {
            "thread_id": run_config.thread_id,
            "run_id": run_config.run_id,
        },
        "recursion_limit": run_config.recursion_limit,
    }
