from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from app.logger import logger


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
MODELS_PATH = PROJECT_ROOT / "models.txt"


def _load_dotenv() -> None:
    loaded = load_dotenv(dotenv_path=str(ENV_PATH), override=False)
    logger.info("Loaded env from {path} (found={found})", path=ENV_PATH, found=loaded)


def load_model_list(path: Path = MODELS_PATH) -> list[str]:
    if not path.exists():
        logger.warning("Model list not found at {path}", path=path)
        return []
    models = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    logger.info("Loaded {count} models from {path}", count=len(models), path=path)
    return models


@dataclass(frozen=True)
class Settings:
    llm_api_url: str
    llm_api_key: str
    default_router_model: str
    default_synthesis_model: str
    available_models: tuple[str, ...]
    database_url: str
    enable_llm_sql_generation: bool
    trace_jsonl_path: str
    enable_langfuse: bool
    langfuse_project_name: str
    langfuse_project_id: str
    langfuse_org_name: str
    langfuse_org_id: str
    langfuse_cloud_region: str
    prompt_cache_ttl_seconds: int
    enable_mcp_tool_client: bool
    mcp_transport: str
    mcp_http_url: str
    mcp_stdio_command: str
    mcp_stdio_args: tuple[str, ...]
    # Node-specific model configuration (for future flexibility)
    model_leader: str
    model_router: str
    model_synthesis: str
    model_sql_generation: str
    model_context_detection: str
    model_task_planner: str
    model_aggregation: str
    model_fallback: str
    model_report_planner: str
    model_report_writer: str
    model_report_critic: str


def _env_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    _load_dotenv()

    models = load_model_list()

    # Default to gpt-4o for higher token limits (12288 -> 128k context)
    default_model = os.getenv("DEFAULT_MODEL", "gh/gpt-4o")
    default_router_model = os.getenv("DEFAULT_ROUTER_MODEL", default_model)
    default_synthesis_model = os.getenv("DEFAULT_SYNTHESIS_MODEL", default_model)

    # Node-specific models (can be overridden via env vars for flexibility)
    model_leader = os.getenv("MODEL_LEADER", default_model)
    model_router = os.getenv("MODEL_ROUTER", default_router_model)
    model_synthesis = os.getenv("MODEL_SYNTHESIS", default_synthesis_model)
    model_sql_generation = os.getenv("MODEL_SQL_GENERATION", default_model)
    model_context_detection = os.getenv("MODEL_CONTEXT_DETECTION", default_model)
    model_task_planner = os.getenv("MODEL_TASK_PLANNER", default_model)
    model_aggregation = os.getenv("MODEL_AGGREGATION", default_model)
    model_fallback = os.getenv(
        "MODEL_FALLBACK", "gh/gpt-4o-mini"
    )  # Keep mini for simple fallback
    model_report_planner = os.getenv("MODEL_REPORT_PLANNER", model_leader)
    model_report_writer = os.getenv("MODEL_REPORT_WRITER", model_synthesis)
    model_report_critic = os.getenv("MODEL_REPORT_CRITIC", model_leader)

    settings = Settings(
        llm_api_url=os.getenv(
            "LLM_API_URL",
            "https://api.openai.com/v1/chat/completions",
        ),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        default_router_model=default_router_model,
        default_synthesis_model=default_synthesis_model,
        available_models=tuple(models),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/postgres",
        ),
        enable_llm_sql_generation=_env_bool(
            os.getenv("ENABLE_LLM_SQL_GENERATION"), True
        ),
        trace_jsonl_path=os.getenv(
            "TRACE_JSONL_PATH",
            str(PROJECT_ROOT / "evals" / "reports" / "traces.jsonl"),
        ),
        enable_langfuse=_env_bool(os.getenv("ENABLE_LANGFUSE"), True),
        prompt_cache_ttl_seconds=_env_int(os.getenv("PROMPT_CACHE_TTL_SECONDS"), 300),
        enable_mcp_tool_client=_env_bool(os.getenv("ENABLE_MCP_TOOL_CLIENT"), False),
        mcp_transport=os.getenv("MCP_TRANSPORT", "streamable-http"),
        mcp_http_url=os.getenv("MCP_HTTP_URL", "http://127.0.0.1:8000/mcp"),
        mcp_stdio_command=os.getenv("MCP_STDIO_COMMAND", "uv"),
        mcp_stdio_args=tuple(
            item.strip()
            for item in os.getenv(
                "MCP_STDIO_ARGS",
                "run,python,-m,mcp_server.server,--transport,stdio",
            ).split(",")
            if item.strip()
        ),
        langfuse_project_name=os.getenv("LANGFUSE_PROJECT_NAME", "da-agent-project"),
        langfuse_project_id=os.getenv("LANGFUSE_PROJECT_ID", ""),
        langfuse_org_name=os.getenv("LANGFUSE_ORG_NAME", ""),
        langfuse_org_id=os.getenv("LANGFUSE_ORG_ID", ""),
        langfuse_cloud_region=os.getenv("LANGFUSE_CLOUD_REGION", "EU"),
        # Node-specific model configuration
        model_leader=model_leader,
        model_router=model_router,
        model_synthesis=model_synthesis,
        model_sql_generation=model_sql_generation,
        model_context_detection=model_context_detection,
        model_task_planner=model_task_planner,
        model_aggregation=model_aggregation,
        model_fallback=model_fallback,
        model_report_planner=model_report_planner,
        model_report_writer=model_report_writer,
        model_report_critic=model_report_critic,
    )

    if not settings.llm_api_key:
        logger.warning(
            "LLM_API_KEY is empty. API calls will fail until key is provided."
        )

    logger.info(
        "Settings ready (router_model={router}, synthesis_model={synthesis}, api_url={url})",
        router=settings.default_router_model,
        synthesis=settings.default_synthesis_model,
        url=settings.llm_api_url,
    )
    return settings
