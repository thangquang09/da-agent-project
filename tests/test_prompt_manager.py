from app.config import load_settings
from app.prompts.manager import PromptManager


def test_router_manager_fallback(monkeypatch):
    monkeypatch.setenv("ENABLE_LANGFUSE", "0")
    load_settings.cache_clear()
    manager = PromptManager()
    messages = manager.router_messages("bạn có thể làm gì")
    assert any("intent router" in msg["content"] for msg in messages)
