"""Minimal MCP-compatible server package for DA Agent Lab."""

__all__ = [
    "create_app",
]
def create_app():
    from mcp_server.server import create_app as _create_app

    return _create_app()
