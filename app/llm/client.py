from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, TypedDict
from urllib import error, request

from app.config import Settings, load_settings
from app.logger import logger


class ChatMessage(TypedDict):
    role: str
    content: str


@dataclass
class LLMClient:
    settings: Settings

    @classmethod
    def from_env(cls) -> "LLMClient":
        logger.info("Initializing LLMClient from environment")
        return cls(settings=load_settings())

    def chat_completion(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        stream: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """OpenAI-compatible chat completion with enforced stream=False."""
        if stream:
            logger.error("Rejected request because stream=true is not allowed")
            raise ValueError("stream must be false for this API profile")

        if not self.settings.llm_api_key:
            logger.error("LLM_API_KEY is missing")
            raise ValueError("LLM_API_KEY is missing")

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if extra:
            payload.update(extra)

        logger.info(
            "Calling LLM API (model={model}, messages={message_count}, temperature={temperature}, stream={stream})",
            model=model,
            message_count=len(messages),
            temperature=temperature,
            stream=False,
        )

        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=self.settings.llm_api_url,
            method="POST",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.llm_api_key}",
            },
        )

        try:
            with request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")
                logger.info("LLM API response received (status={status})", status=resp.status)
        except error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            logger.exception("LLM API HTTP error {status}: {body}", status=exc.code, body=err_body[:500])
            raise RuntimeError(f"LLM API HTTP error {exc.code}: {err_body}") from exc
        except error.URLError as exc:
            logger.exception("LLM API connection error: {reason}", reason=exc.reason)
            raise RuntimeError(f"LLM API connection error: {exc.reason}") from exc

        try:
            parsed = json.loads(body)
            logger.info("LLM API response parsed successfully")
            return parsed
        except json.JSONDecodeError as exc:
            logger.exception("LLM API returned non-JSON body")
            raise RuntimeError(f"LLM API returned non-JSON body: {body[:500]}") from exc
