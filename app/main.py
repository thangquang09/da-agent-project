from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.graph import build_sql_v1_graph, new_run_config, to_langgraph_config
from app.logger import logger


def run_query(user_query: str, recursion_limit: int = 25, db_path: str | None = None) -> dict:
    graph = build_sql_v1_graph()
    run_cfg = new_run_config(recursion_limit=recursion_limit)
    graph_input: dict[str, str] = {"user_query": user_query}
    if db_path:
        graph_input["target_db_path"] = str(Path(db_path))
    output = graph.invoke(
        graph_input,
        config=to_langgraph_config(run_cfg),
    )
    payload = output.get("final_payload", {})
    payload["run_id"] = output.get("run_id", run_cfg.run_id)
    payload["intent"] = output.get("intent", payload.get("intent", "unknown"))
    payload["intent_reason"] = output.get("intent_reason", "")
    payload["errors"] = output.get("errors", [])
    payload["step_count"] = output.get("step_count", payload.get("step_count"))
    return payload


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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_query(args.query, recursion_limit=args.recursion_limit, db_path=args.db_path)
    logger.info("Query completed with confidence={confidence}", confidence=result.get("confidence"))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
