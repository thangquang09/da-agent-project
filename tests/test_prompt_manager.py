from app.config import load_settings
from app.prompts.manager import PromptManager


def test_router_manager_fallback(monkeypatch):
    monkeypatch.setenv("ENABLE_LANGFUSE", "0")
    load_settings.cache_clear()
    manager = PromptManager()
    messages = manager.router_messages("bạn có thể làm gì")
    assert any("intent router" in msg["content"] for msg in messages)


def test_apply_variables_handles_conditionals():
    import os

    os.environ["ENABLE_LANGFUSE"] = "0"
    load_settings.cache_clear()
    manager = PromptManager()
    template = "Hello{{#if name}} {{name}}{{/if}}!"
    result = manager._apply_variables(template, {"name": "World"})
    assert result == "Hello World!"

    result_empty = manager._apply_variables(template, {"name": ""})
    assert result_empty == "Hello!"

    result_missing = manager._apply_variables(template, {})
    assert result_missing == "Hello!"


def test_apply_variables_handles_multiline_conditionals():
    import os

    os.environ["ENABLE_LANGFUSE"] = "0"
    load_settings.cache_clear()
    manager = PromptManager()
    template = """Line1
{{#if show}}
Line2
{{/if}}Line3"""
    result_show = manager._apply_variables(template, {"show": "yes"})
    assert "Line2" in result_show
    assert "{{#if show}}" not in result_show

    result_hide = manager._apply_variables(template, {"show": ""})
    assert "Line2" not in result_hide
    assert "{{#if show}}" not in result_hide


def test_sql_prompt_conditional_semantic_context():
    import os

    os.environ["ENABLE_LANGFUSE"] = "0"
    load_settings.cache_clear()
    manager = PromptManager()
    messages = manager.sql_messages(
        query="test query",
        schema_context="test schema",
        dataset_context="test dataset",
        semantic_context="test semantic",
    )
    content = messages[1]["content"]
    assert "Relevant semantic context:" in content
    assert "test semantic" in content

    messages_no_semantic = manager.sql_messages(
        query="test query",
        schema_context="test schema",
        dataset_context="test dataset",
        semantic_context="",
    )
    content_no_semantic = messages_no_semantic[1]["content"]
    assert "{{#if semantic_context}}" not in content_no_semantic
    assert "{{/if}}" not in content_no_semantic
    assert "Relevant semantic context:" not in content_no_semantic
