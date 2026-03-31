from __future__ import annotations

import argparse
import sys
from typing import Any

from app.logger import logger
from mcp_server.tools import (
    tool_auto_register_csv,
    tool_dataset_context,
    tool_get_schema,
    tool_profile_csv,
    tool_query_sql,
    tool_retrieve_metric_definition,
    tool_validate_csv,
)

try:
    from mcp.server.fastmcp import FastMCP
except Exception as exc:  # noqa: BLE001
    FastMCP = None
    _import_error = exc
else:
    _import_error = None


def _configure_stdio_logging() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO", backtrace=False, diagnose=False)


def create_app():
    """Create MCP ASGI app exposing DA Agent tools."""

    if FastMCP is None:
        raise RuntimeError(
            "mcp is not installed. Install with `pip install mcp`"
        ) from _import_error

    server = FastMCP(
        "da-agent-mcp", json_response=True, stateless_http=True, log_level="ERROR"
    )

    @server.tool()
    def get_schema(db_path: str | None = None) -> Any:  # noqa: D401
        return tool_get_schema(db_path=db_path)

    @server.tool()
    def dataset_context(db_path: str | None = None) -> Any:  # noqa: D401
        return tool_dataset_context(db_path=db_path)

    @server.tool()
    def retrieve_metric_definition(query: str, top_k: int = 4) -> Any:  # noqa: D401
        return tool_retrieve_metric_definition(query=query, top_k=top_k)

    @server.tool()
    def query_sql(
        sql: str, row_limit: int | None = None, db_path: str | None = None
    ) -> Any:  # noqa: D401
        return tool_query_sql(sql=sql, row_limit=row_limit, db_path=db_path)

    @server.tool()
    def validate_csv(file_path: str) -> Any:  # noqa: D401
        return tool_validate_csv(file_path=file_path)

    @server.tool()
    def profile_csv(
        file_path: str,
        table_name: str | None = None,
        encoding: str | None = None,
        delimiter: str | None = None,
    ) -> Any:  # noqa: D401
        return tool_profile_csv(
            file_path=file_path,
            table_name=table_name,
            encoding=encoding,
            delimiter=delimiter,
        )

    @server.tool()
    def auto_register_csv(
        file_path: str,
        table_name: str | None = None,
        db_path: str | None = None,
    ) -> Any:  # noqa: D401
        return tool_auto_register_csv(
            file_path=file_path,
            table_name=table_name,
            db_path=db_path,
        )

    return server.streamable_http_app()


def _build_server() -> Any:
    if FastMCP is None:
        logger.error("modelcontextprotocol is missing; cannot start MCP server.")
        raise RuntimeError("mcp is missing")

    server = FastMCP(
        "da-agent-mcp", json_response=True, stateless_http=True, log_level="ERROR"
    )

    @server.tool()
    def get_schema(db_path: str | None = None) -> Any:
        return tool_get_schema(db_path=db_path)

    @server.tool()
    def dataset_context(db_path: str | None = None) -> Any:
        return tool_dataset_context(db_path=db_path)

    @server.tool()
    def retrieve_metric_definition(query: str, top_k: int = 4) -> Any:
        return tool_retrieve_metric_definition(query=query, top_k=top_k)

    @server.tool()
    def query_sql(
        sql: str, row_limit: int | None = None, db_path: str | None = None
    ) -> Any:
        return tool_query_sql(sql=sql, row_limit=row_limit, db_path=db_path)

    @server.tool()
    def validate_csv(file_path: str) -> Any:
        return tool_validate_csv(file_path=file_path)

    @server.tool()
    def profile_csv(
        file_path: str,
        table_name: str | None = None,
        encoding: str | None = None,
        delimiter: str | None = None,
    ) -> Any:
        return tool_profile_csv(
            file_path=file_path,
            table_name=table_name,
            encoding=encoding,
            delimiter=delimiter,
        )

    @server.tool()
    def auto_register_csv(
        file_path: str,
        table_name: str | None = None,
        db_path: str | None = None,
    ) -> Any:
        return tool_auto_register_csv(
            file_path=file_path,
            table_name=table_name,
            db_path=db_path,
        )

    return server


def main() -> None:
    if FastMCP is None:
        logger.error("mcp package is missing; cannot start MCP server.")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Run DA Agent MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="streamable-http",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = _build_server()
    if args.transport == "stdio":
        _configure_stdio_logging()
        logger.info("Starting MCP server with stdio transport")
        server.run(transport="stdio")
        return

    import uvicorn

    app = server.streamable_http_app()
    logger.info(
        "Starting MCP server on http://{host}:{port}", host=args.host, port=args.port
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
