from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, TypedDict
from urllib import error, request

from app.config import Settings, load_settings
from app.logger import logger


class ChatMessage(TypedDict):
    role: str
    content: str | list[dict[str, Any]]


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

        max_retries = 2
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                with request.urlopen(req, timeout=60) as resp:
                    body = resp.read().decode("utf-8")
                    logger.info("LLM API response received (status={status})", status=resp.status)
                last_exc = None
                break
            except error.HTTPError as exc:
                err_body = exc.read().decode("utf-8", errors="replace")
                is_retryable = exc.code == 429 or exc.code >= 500
                if is_retryable and attempt < max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "LLM API retryable error {status}, retrying in {wait}s (attempt={attempt}/{max_retries})",
                        status=exc.code,
                        wait=wait,
                        attempt=attempt + 1,
                        max_retries=max_retries,
                    )
                    time.sleep(wait)
                    last_exc = exc
                    continue
                logger.exception("LLM API HTTP error {status}: {body}", status=exc.code, body=err_body[:500])
                raise RuntimeError(f"LLM API HTTP error {exc.code}: {err_body}") from exc
            except error.URLError as exc:
                if attempt < max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "LLM API connection error, retrying in {wait}s (attempt={attempt}/{max_retries}): {reason}",
                        wait=wait,
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        reason=exc.reason,
                    )
                    time.sleep(wait)
                    last_exc = exc
                    continue
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

    def stream_chat_completion(
        self,
        messages: list[ChatMessage],
        model: str,
        on_token: Callable[[str], None],
        temperature: float = 0.2,
        max_tokens: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Stream chat completion tokens. Calls *on_token* for each content delta.

        Returns the accumulated full response in the same shape as
        ``chat_completion`` once all tokens have been consumed.
        """
        if not self.settings.llm_api_key:
            logger.error("LLM_API_KEY is missing")
            raise ValueError("LLM_API_KEY is missing")

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if extra:
            payload.update(extra)

        logger.info(
            "Calling LLM API STREAMING (model={model}, messages={message_count})",
            model=model,
            message_count=len(messages),
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

        max_retries = 2
        accumulated = ""
        stream_usage: dict[str, Any] | None = None
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            accumulated = ""
            stream_usage = None
            try:
                with request.urlopen(req, timeout=120) as resp:
                    for raw_line in resp:
                        line = raw_line.decode("utf-8").strip()
                        if not line:
                            continue
                        # Handle SSE lines: "data: {...}" or "data: [DONE]"
                        if line.startswith("data: "):
                            payload_str = line[6:]
                            if payload_str.strip() == "[DONE]":
                                break
                            try:
                                chunk = json.loads(payload_str)
                                if isinstance(chunk.get("usage"), dict):
                                    stream_usage = chunk["usage"]

                                choices = chunk.get("choices")
                                if not isinstance(choices, list) or not choices:
                                    continue

                                delta_payload = choices[0].get("delta", {})
                                if not isinstance(delta_payload, dict):
                                    continue

                                delta = delta_payload.get("content", "")
                                if isinstance(delta, str) and delta:
                                    accumulated += delta
                                    on_token(delta)
                            except json.JSONDecodeError:
                                continue
                last_exc = None
                break
            except error.HTTPError as exc:
                err_body = exc.read().decode("utf-8", errors="replace")
                is_retryable = exc.code == 429 or exc.code >= 500
                if is_retryable and attempt < max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "LLM API STREAM retryable error {status}, retrying in {wait}s (attempt={attempt}/{max_retries})",
                        status=exc.code,
                        wait=wait,
                        attempt=attempt + 1,
                        max_retries=max_retries,
                    )
                    time.sleep(wait)
                    last_exc = exc
                    continue
                logger.exception("LLM API HTTP error {status}: {body}", status=exc.code, body=err_body[:500])
                raise RuntimeError(f"LLM API HTTP error {exc.code}: {err_body}") from exc
            except error.URLError as exc:
                if attempt < max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "LLM API STREAM connection error, retrying in {wait}s (attempt={attempt}/{max_retries}): {reason}",
                        wait=wait,
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        reason=exc.reason,
                    )
                    time.sleep(wait)
                    last_exc = exc
                    continue
                logger.exception("LLM API connection error: {reason}", reason=exc.reason)
                raise RuntimeError(f"LLM API connection error: {exc.reason}") from exc

        logger.info("LLM API streaming complete ({length} chars)", length=len(accumulated))

        # Return in same shape as chat_completion
        result: dict[str, Any] = {
            "choices": [{"message": {"content": accumulated}}],
        }
        if stream_usage is not None:
            result["usage"] = stream_usage
        usage = self._normalize_usage(result)
        if usage is not None:
            result["_usage_normalized"] = usage
            result["_cost_usd_estimate"] = self._estimate_cost_usd(model=model, usage=usage)
        return result

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
