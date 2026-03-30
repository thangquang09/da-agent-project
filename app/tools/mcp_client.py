from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import urlopen

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from app.config import load_settings
from app.logger import logger

_MCP_SERVER_PROC: subprocess.Popen[str] | None = None
_MCP_SERVER_LOCK = Lock()
_MCP_SERVER_LOG = Path("/tmp/da_agent_mcp_server.log")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_http_server_ready(url: str) -> bool:
    try:
        with urlopen(url, timeout=0.5) as _resp:  # noqa: S310
            return True
    except HTTPError as exc:
        return exc.code in {400, 404, 405, 406}
    except Exception:
        return False


def _ensure_http_server() -> None:
    global _MCP_SERVER_PROC
    settings = load_settings()
    url = settings.mcp_http_url
    if _is_http_server_ready(url):
        return

    with _MCP_SERVER_LOCK:
        if _is_http_server_ready(url):
            return
        if _MCP_SERVER_PROC is not None and _MCP_SERVER_PROC.poll() is None:
            # Process exists but endpoint is not ready yet.
            pass
        else:
            # NOTE: launch server matching MCP_HTTP_URL so readiness check doesn't hang
            # when users override host/port/path.
            from urllib.parse import urlparse

            parsed = urlparse(url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 8000

            cmd = [
                settings.mcp_stdio_command,
                "run",
                "python",
                "-m",
                "mcp_server.server",
                "--transport",
                "streamable-http",
                "--host",
                host,
                "--port",
                str(port),
            ]
            logger.info("Starting persistent MCP HTTP server")
            log_handle = _MCP_SERVER_LOG.open("a", encoding="utf-8")
            _MCP_SERVER_PROC = subprocess.Popen(  # noqa: S603
                cmd,
                cwd=str(_project_root()),
                stdout=log_handle,
                stderr=log_handle,
                text=True,
            )

        # wait until server is ready
        deadline = time.time() + 20.0
        while time.time() < deadline:
            if _MCP_SERVER_PROC is not None and _MCP_SERVER_PROC.poll() is not None:
                raise RuntimeError(
                    f"MCP HTTP server exited early (code={_MCP_SERVER_PROC.returncode}). "
                    f"See {_MCP_SERVER_LOG}"
                )
            if _is_http_server_ready(url):
                return
            time.sleep(0.1)
        raise RuntimeError(f"MCP HTTP server failed to start in time. See {_MCP_SERVER_LOG}")


async def _call_tool_async(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = load_settings()
    if settings.mcp_transport == "streamable-http":
        _ensure_http_server()
        async with streamable_http_client(settings.mcp_http_url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(name=name, arguments=arguments or {})
                if result.isError:
                    raise RuntimeError(f"MCP tool call failed: {name}")
                if result.structuredContent is not None and isinstance(result.structuredContent, dict):
                    return result.structuredContent
                if result.content:
                    text_blocks = [getattr(block, "text", "") for block in result.content]
                    joined = "\n".join(text for text in text_blocks if text)
                    if joined:
                        try:
                            parsed = json.loads(joined)
                            if isinstance(parsed, dict):
                                return parsed
                        except json.JSONDecodeError:
                            pass
                    return {"content": [text for text in text_blocks if text]}
        return {}

    server = StdioServerParameters(
        command=settings.mcp_stdio_command,
        args=list(settings.mcp_stdio_args),
        cwd=_project_root(),
    )
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(name=name, arguments=arguments or {})
            if result.isError:
                raise RuntimeError(f"MCP tool call failed: {name}")
            if result.structuredContent is not None and isinstance(result.structuredContent, dict):
                return result.structuredContent
            if result.content:
                text_blocks = [getattr(block, "text", "") for block in result.content]
                joined = "\n".join(text for text in text_blocks if text)
                if joined:
                    try:
                        parsed = json.loads(joined)
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        pass
                return {"content": [text for text in text_blocks if text]}
    return {}


def call_mcp_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = load_settings()
    logger.info("Calling MCP tool '{name}' over {transport}", name=name, transport=settings.mcp_transport)
    return anyio.run(_call_tool_async, name, arguments or {})
