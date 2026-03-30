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

    DEFAULT_MODEL_PRICING_USD_PER_1M = {
        "gh/gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gh/gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4o": {"input": 2.50, "output": 10.00},
    }

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
            usage = self._normalize_usage(parsed)
            if usage is not None:
                parsed["_usage_normalized"] = usage
                parsed["_cost_usd_estimate"] = self._estimate_cost_usd(model=model, usage=usage)
            logger.info("LLM API response parsed successfully")
            return parsed
        except json.JSONDecodeError as exc:
            logger.exception("LLM API returned non-JSON body")
            raise RuntimeError(f"LLM API returned non-JSON body: {body[:500]}") from exc

    @staticmethod
    def _as_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _normalize_usage(self, parsed: dict[str, Any]) -> dict[str, int] | None:
        usage = parsed.get("usage")
        if not isinstance(usage, dict):
            return None

        prompt_tokens = self._as_int(usage.get("prompt_tokens"))
        completion_tokens = self._as_int(usage.get("completion_tokens"))
        total_tokens = self._as_int(usage.get("total_tokens"))
        reasoning_tokens = self._as_int(usage.get("reasoning_tokens")) or 0

        # Compatibility fallback for non-standard usage schemas.
        if prompt_tokens is None:
            prompt_tokens = self._as_int(usage.get("input_tokens"))
        if completion_tokens is None:
            completion_tokens = self._as_int(usage.get("output_tokens"))
        if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
            total_tokens = prompt_tokens + completion_tokens

        if prompt_tokens is None and completion_tokens is None and total_tokens is None:
            return None

        return {
            "prompt_tokens": prompt_tokens or 0,
            "completion_tokens": completion_tokens or 0,
            "total_tokens": total_tokens or 0,
            "reasoning_tokens": reasoning_tokens,
        }

    def _estimate_cost_usd(self, model: str, usage: dict[str, int]) -> float | None:
        pricing = self.DEFAULT_MODEL_PRICING_USD_PER_1M.get(model)
        if pricing is None:
            return None
        input_cost = (usage.get("prompt_tokens", 0) / 1_000_000) * float(pricing["input"])
        output_cost = (usage.get("completion_tokens", 0) / 1_000_000) * float(pricing["output"])
        return round(input_cost + output_cost, 8)
