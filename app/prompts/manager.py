from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Literal

from app.config import load_settings
from app.logger import logger
from app.prompts.router import ROUTER_PROMPT_DEFINITION
from app.prompts.sql import SQL_PROMPT_DEFINITION


@dataclass
class _PromptCacheEntry:
    prompt: Any
    expires_at: float


class PromptManager:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.langfuse_client = self._init_langfuse_client()
        self.cache: dict[str, _PromptCacheEntry] = {}
        self.cache_ttl = getattr(self.settings, "prompt_cache_ttl_seconds", 300)

    def _init_langfuse_client(self) -> Any | None:
        if not self.settings.enable_langfuse:
            return None
        host = (os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") or "").strip().strip('"').strip("'")
        if host and not os.getenv("LANGFUSE_HOST"):
            os.environ["LANGFUSE_HOST"] = host
        required = ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"]
        if not all(os.getenv(key) for key in required):
            logger.warning("Langfuse prompt manager missing credentials, will use local fallbacks")
            return None
        try:
            from langfuse import get_client  # type: ignore

            return get_client()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Langfuse prompt manager disabled: {error}", error=str(exc))
            return None

    def _get_prompt(self, definition: Any) -> Any | None:
        now = time.time()
        cache_entry = self.cache.get(definition.name)
        if cache_entry and cache_entry.expires_at > now:
            return cache_entry.prompt
        if self.langfuse_client is None:
            return None
        try:
            try:
                prompt = self.langfuse_client.get_prompt(
                    definition.name,
                    type=definition.prompt_type,
                    fallback=definition.messages,
                    labels=["production"],
                )
            except TypeError:
                # Backward-compatible with older langfuse clients that don't support `labels`.
                prompt = self.langfuse_client.get_prompt(
                    definition.name,
                    type=definition.prompt_type,
                    fallback=definition.messages,
                )
            self.cache[definition.name] = _PromptCacheEntry(prompt=prompt, expires_at=now + self.cache_ttl)
            return prompt
        except Exception as exc:  # noqa: BLE001
            logger.warning("Langfuse prompt fetch failed for {name}: {error}", name=definition.name, error=str(exc))
            return None

    def _clean_template(self, template: str) -> str:
        return template.replace("{{", "{").replace("}}", "}")

    def _apply_variables(self, template: str, variables: dict[str, Any]) -> str:
        content = template
        for key, value in variables.items():
            placeholder = f"{{{{{key}}}}}"
            content = content.replace(placeholder, str(value or ""))
        return content

    def _compile_local_messages(self, definition: Any, variables: dict[str, Any]) -> list[dict[str, str]]:
        compiled: list[dict[str, str]] = []
        for message in definition.messages:
            compiled.append(
                {
                    "role": message["role"],
                    "content": self._apply_variables(message["content"], variables),
                }
            )
        return compiled

    def _compile_prompt(self, definition: Any, variables: dict[str, Any]) -> list[dict[str, str]]:
        prompt = self._get_prompt(definition)
        if prompt:
            try:
                compiled = prompt.compile(**variables)
                if isinstance(compiled, list):
                    return compiled
                if isinstance(compiled, str):
                    return [{"role": "user", "content": compiled}]
            except Exception as exc:  # noqa: BLE001
                logger.warning("Langfuse prompt compile failed for {name}: {error}", name=definition.name, error=str(exc))
        return self._compile_local_messages(definition, variables)

    def router_messages(self, query: str) -> list[dict[str, str]]:
        return self._compile_prompt(ROUTER_PROMPT_DEFINITION, {"query": query})

    def sql_messages(self, query: str, schema_context: str, dataset_context: str = "") -> list[dict[str, str]]:
        return self._compile_prompt(
            SQL_PROMPT_DEFINITION,
            {
                "query": query,
                "schema_context": schema_context or "",
                "dataset_context": dataset_context or "",
            },
        )


prompt_manager = PromptManager()
