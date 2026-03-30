from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydotenv import Environment

from app.logger import logger


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
MODELS_PATH = PROJECT_ROOT / "models.txt"


def _load_dotenv(path: Path) -> None:
    env_file = Environment(file_path=str(path), check_file_exists=False)
    loaded_keys = 0

    for key, value in env_file.items():
        if key and key not in os.environ:
            os.environ[key] = value
            loaded_keys += 1

    logger.info("Loaded {count} env keys from {path}", count=loaded_keys, path=path)


def load_model_list(path: Path = MODELS_PATH) -> list[str]:
    if not path.exists():
        logger.warning("Model list not found at {path}", path=path)
        return []
    models = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    logger.info("Loaded {count} models from {path}", count=len(models), path=path)
    return models


@dataclass(frozen=True)
class Settings:
    llm_api_url: str
    llm_api_key: str
    default_router_model: str
    default_synthesis_model: str
    available_models: tuple[str, ...]
    sqlite_db_path: str
    enable_llm_sql_generation: bool
    trace_jsonl_path: str
    enable_langfuse: bool


def _env_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    _load_dotenv(ENV_PATH)

    models = load_model_list()
    default_router_model = os.getenv("DEFAULT_ROUTER_MODEL", "gh/gpt-4o-mini")
    default_synthesis_model = os.getenv("DEFAULT_SYNTHESIS_MODEL", "gh/gpt-4o")

    settings = Settings(
        llm_api_url=os.getenv(
            "LLM_API_URL",
            "https://thangquangly0909--9router-web.modal.run/v1/chat/completions",
        ),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        default_router_model=default_router_model,
        default_synthesis_model=default_synthesis_model,
        available_models=tuple(models),
        sqlite_db_path=os.getenv(
            "SQLITE_DB_PATH",
            str(PROJECT_ROOT / "data" / "warehouse" / "analytics.db"),
        ),
        enable_llm_sql_generation=_env_bool(os.getenv("ENABLE_LLM_SQL_GENERATION"), False),
        trace_jsonl_path=os.getenv(
            "TRACE_JSONL_PATH",
            str(PROJECT_ROOT / "evals" / "reports" / "traces.jsonl"),
        ),
        enable_langfuse=_env_bool(os.getenv("ENABLE_LANGFUSE"), True),
    )

    if not settings.llm_api_key:
        logger.warning("LLM_API_KEY is empty. API calls will fail until key is provided.")

    logger.info(
        "Settings ready (router_model={router}, synthesis_model={synthesis}, api_url={url})",
        router=settings.default_router_model,
        synthesis=settings.default_synthesis_model,
        url=settings.llm_api_url,
    )
    return settings
