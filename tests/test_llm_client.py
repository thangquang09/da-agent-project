from __future__ import annotations

import json

from app.config import load_settings
from app.llm.client import LLMClient


class _FakeStreamingResponse:
    def __init__(self, lines: list[str], status: int = 200):
        self._lines = [line.encode("utf-8") for line in lines]
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        return iter(self._lines)


def test_stream_chat_completion_ignores_empty_choice_chunks_and_keeps_usage(
    monkeypatch,
):
    settings = load_settings()
    client = LLMClient(settings=settings)
    tokens: list[str] = []

    chunks = [
        'data: {"choices":[],"created":1,"object":"chat.completion.chunk"}\n',
        "\n",
        'data: {"choices":[{"index":0,"delta":{"content":"","role":"assistant"}}]}\n',
        "\n",
        'data: {"choices":[{"index":0,"delta":{"content":"Hello"}}]}\n',
        "\n",
        'data: {"choices":[{"index":0,"delta":{"content":"!"}}],"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}}\n',
        "\n",
        "data: [DONE]\n",
    ]

    monkeypatch.setattr(
        "app.llm.client.request.urlopen",
        lambda req, timeout=120: _FakeStreamingResponse(chunks),
    )

    result = client.stream_chat_completion(
        messages=[{"role": "user", "content": "Say hello"}],
        model="gh/gpt-4o-mini",
        on_token=tokens.append,
    )

    assert "".join(tokens) == "Hello!"
    assert result["choices"][0]["message"]["content"] == "Hello!"
    assert result["_usage_normalized"] == {
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "total_tokens": 12,
        "reasoning_tokens": 0,
    }
    assert result["_cost_usd_estimate"] == 0.0000027


def test_stream_chat_completion_skips_non_json_lines(monkeypatch):
    settings = load_settings()
    client = LLMClient(settings=settings)
    tokens: list[str] = []

    chunks = [
        "data: not-json\n",
        "\n",
        f'data: {json.dumps({"choices": [{"index": 0, "delta": {"content": "OK"}}]})}\n',
        "\n",
        "data: [DONE]\n",
    ]

    monkeypatch.setattr(
        "app.llm.client.request.urlopen",
        lambda req, timeout=120: _FakeStreamingResponse(chunks),
    )

    result = client.stream_chat_completion(
        messages=[{"role": "user", "content": "Ping"}],
        model="gh/gpt-4o-mini",
        on_token=tokens.append,
    )

    assert tokens == ["OK"]
    assert result["choices"][0]["message"]["content"] == "OK"
