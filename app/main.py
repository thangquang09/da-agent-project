from __future__ import annotations

import argparse
import json

from app.graph import build_sql_v1_graph, new_run_config, to_langgraph_config
from app.logger import logger


def run_query(user_query: str, recursion_limit: int = 25) -> dict:
    graph = build_sql_v1_graph()
    run_cfg = new_run_config(recursion_limit=recursion_limit)
    output = graph.invoke(
        {"user_query": user_query},
        config=to_langgraph_config(run_cfg),
    )
    payload = output.get("final_payload", {})
    payload["run_id"] = output.get("run_id", run_cfg.run_id)
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_query(args.query, recursion_limit=args.recursion_limit)
    logger.info("Query completed with confidence={confidence}", confidence=result.get("confidence"))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

