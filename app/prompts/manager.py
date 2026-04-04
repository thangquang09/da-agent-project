from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any, Literal

from app.config import load_settings
from app.logger import logger
from app.prompts.analysis import ANALYSIS_PROMPT_DEFINITION
from app.prompts.classifier import RETRIEVAL_TYPE_CLASSIFIER_PROMPT
from app.prompts.context_detection import CONTEXT_DETECTION_PROMPT_DEFINITION
from app.prompts.continuity import CONTINUITY_DETECTION_PROMPT_DEFINITION
from app.prompts.decomposition import TASK_DECOMPOSITION_PROMPT
from app.prompts.evaluation import GROUNDEDNESS_EVALUATION_PROMPT
from app.prompts.fallback import FALLBACK_ASSISTANT_PROMPT
from app.prompts.leader import LEADER_AGENT_PROMPT_DEFINITION
from app.prompts.router import ROUTER_PROMPT_DEFINITION
from app.prompts.sql import SQL_PROMPT_DEFINITION
from app.prompts.sql_worker import SQL_WORKER_GENERATION_PROMPT
from app.prompts.synthesis import SYNTHESIS_PROMPT_DEFINITION
from app.prompts.visualization import VISUALIZATION_CODE_GENERATION_PROMPT


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
        host = (
            (os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") or "")
            .strip()
            .strip('"')
            .strip("'")
        )
        if host and not os.getenv("LANGFUSE_HOST"):
            os.environ["LANGFUSE_HOST"] = host
        required = ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"]
        if not all(os.getenv(key) for key in required):
            logger.warning(
                "Langfuse prompt manager missing credentials, will use local fallbacks"
            )
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
            self.cache[definition.name] = _PromptCacheEntry(
                prompt=prompt, expires_at=now + self.cache_ttl
            )
            return prompt
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Langfuse prompt fetch failed for {name}: {error}",
                name=definition.name,
                error=str(exc),
            )
            return None

    def _clean_template(self, template: str) -> str:
        return template.replace("{{", "{").replace("}}", "}")

    def _apply_variables(self, template: str, variables: dict[str, Any]) -> str:
        content = template

        # Process {{#if var}}...{{/if}} conditionals
        pattern = r"\{\{#if\s+(\w+)\}\}(.*?)\{\{/if\}\}"
        for match in re.finditer(pattern, template, re.DOTALL):
            var_name = match.group(1)
            block_content = match.group(2)
            var_value = variables.get(var_name, "")
            if var_value:
                # Replace the conditional block with its content (variables will be replaced below)
                content = content.replace(match.group(0), block_content)
            else:
                # Remove the entire conditional block
                content = content.replace(match.group(0), "")

        # Replace remaining variables
        for key, value in variables.items():
            placeholder = f"{{{{{key}}}}}"
            content = content.replace(placeholder, str(value or ""))

        return content

    def _compile_local_messages(
        self, definition: Any, variables: dict[str, Any]
    ) -> list[dict[str, str]]:
        compiled: list[dict[str, str]] = []
        for message in definition.messages:
            compiled.append(
                {
                    "role": message["role"],
                    "content": self._apply_variables(message["content"], variables),
                }
            )
        return compiled

    def _compile_prompt(
        self, definition: Any, variables: dict[str, Any]
    ) -> list[dict[str, str]]:
        prompt = self._get_prompt(definition)
        if prompt:
            try:
                compiled = prompt.compile(**variables)
                if isinstance(compiled, list):
                    return compiled
                if isinstance(compiled, str):
                    return [{"role": "user", "content": compiled}]
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Langfuse prompt compile failed for {name}: {error}",
                    name=definition.name,
                    error=str(exc),
                )
        return self._compile_local_messages(definition, variables)

    def router_messages(
        self, query: str, session_context: str = ""
    ) -> list[dict[str, str]]:
        return self._compile_prompt(
            ROUTER_PROMPT_DEFINITION,
            {"query": query, "session_context": session_context},
        )

    def context_detection_messages(
        self,
        query: str,
        user_semantic_context: str | None = None,
        uploaded_files: list[str] | None = None,
    ) -> list[dict[str, str]]:
        return self._compile_prompt(
            CONTEXT_DETECTION_PROMPT_DEFINITION,
            {
                "query": query,
                "user_semantic_context": user_semantic_context or "",
                "uploaded_files": uploaded_files or [],
            },
        )

    def sql_messages(
        self,
        query: str,
        schema_context: str,
        dataset_context: str = "",
        semantic_context: str = "",
        session_context: str = "",
        xml_database_context: str = "",
        previous_sql: str | None = None,
        error_message: str | None = None,
    ) -> list[dict[str, str]]:
        # Use self-correction prompt if we have an error context
        if previous_sql and error_message:
            from app.prompts.sql import SQL_SELF_CORRECTION_PROMPT_DEFINITION

            return self._compile_prompt(
                SQL_SELF_CORRECTION_PROMPT_DEFINITION,
                {
                    "query": query,
                    "schema_context": schema_context or "",
                    "dataset_context": dataset_context or "",
                    "semantic_context": semantic_context or "",
                    "session_context": session_context or "",
                    "xml_database_context": xml_database_context or "",
                    "previous_sql": previous_sql,
                    "error_message": error_message,
                },
            )

        # Otherwise use standard prompt
        return self._compile_prompt(
            SQL_PROMPT_DEFINITION,
            {
                "query": query,
                "schema_context": schema_context or "",
                "dataset_context": dataset_context or "",
                "semantic_context": semantic_context or "",
                "session_context": session_context or "",
                "xml_database_context": xml_database_context or "",
            },
        )

    def analysis_messages(
        self,
        query: str,
        sql: str,
        results: list[dict[str, Any]],
        expected_keywords: list[str] | None = None,
    ) -> list[dict[str, str]]:
        import json

        results_json = json.dumps(results, ensure_ascii=False, indent=2)
        keywords_str = ", ".join(expected_keywords) if expected_keywords else ""
        return self._compile_prompt(
            ANALYSIS_PROMPT_DEFINITION,
            {
                "query": query,
                "sql": sql,
                "results": results_json,
                "expected_keywords": keywords_str,
            },
        )

    def synthesis_messages(
        self,
        query: str,
        results: list[dict[str, Any]],
        row_count: int,
        session_context: str = "",
        summary_stats: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        """Generate messages for natural language synthesis from SQL results."""
        import json

        from app.utils.json_serializer import safe_json_dumps

        from app.prompts.synthesis import SYNTHESIS_PROMPT_DEFINITION

        results_json = safe_json_dumps(results, indent=2)
        stats_json = safe_json_dumps(summary_stats, indent=2) if summary_stats else ""
        return self._compile_prompt(
            SYNTHESIS_PROMPT_DEFINITION,
            {
                "query": query,
                "results": results_json,
                "row_count": row_count,
                "session_context": session_context or "",
                "summary_stats": stats_json,
            },
        )

    def retrieval_type_classifier_messages(self, query: str) -> list[dict[str, str]]:
        return self._compile_prompt(
            RETRIEVAL_TYPE_CLASSIFIER_PROMPT,
            {"query": query},
        )

    def fallback_assistant_messages(
        self,
        query: str,
        intent: str,
        errors: list[dict[str, Any]],
        session_context: str = "",
    ) -> list[dict[str, str]]:
        import json

        errors_json = json.dumps(errors, ensure_ascii=False) if errors else "[]"
        return self._compile_prompt(
            FALLBACK_ASSISTANT_PROMPT,
            {
                "query": query,
                "intent": intent,
                "errors": errors_json,
                "session_context": session_context or "",
            },
        )

    def leader_agent_messages(
        self,
        query: str,
        session_context: str = "",
        xml_database_context: str = "",
        scratchpad: str = "",
    ) -> list[dict[str, str]]:
        return self._compile_prompt(
            LEADER_AGENT_PROMPT_DEFINITION,
            {
                "query": query,
                "session_context": session_context or "",
                "xml_database_context": xml_database_context or "",
                "scratchpad": scratchpad or "",
            },
        )

    def task_decomposition_messages(
        self, query: str, schema: str
    ) -> list[dict[str, str]]:
        return self._compile_prompt(
            TASK_DECOMPOSITION_PROMPT,
            {"query": query, "schema": schema},
        )

    def sql_worker_messages(
        self,
        query: str,
        schema: str,
        session_context: str = "",
        xml_database_context: str = "",
    ) -> list[dict[str, str]]:
        return self._compile_prompt(
            SQL_WORKER_GENERATION_PROMPT,
            {
                "query": query,
                "schema": schema,
                "session_context": session_context or "",
                "xml_database_context": xml_database_context or "",
            },
        )

    def visualization_messages(
        self,
        query: str,
        schema_desc: str,
        chart_type: str = "",
    ) -> list[dict[str, str]]:
        return self._compile_prompt(
            VISUALIZATION_CODE_GENERATION_PROMPT,
            {"query": query, "schema_desc": schema_desc, "chart_type": chart_type},
        )

    def continuity_detection_messages(
        self,
        action_type: str,
        intent: str,
        sql: str,
        result_summary: str,
        parameters: str,
        current_query: str,
    ) -> list[dict[str, str]]:
        return self._compile_prompt(
            CONTINUITY_DETECTION_PROMPT_DEFINITION,
            {
                "action_type": action_type,
                "intent": intent,
                "sql": sql,
                "result_summary": result_summary,
                "parameters": parameters,
                "current_query": current_query,
            },
        )

    def groundedness_evaluation_messages(
        self,
        evidence: list[str],
        answer: str,
        expected_keywords: list[str] | None = None,
    ) -> list[dict[str, str]]:
        evidence_text = "\n".join(f"- {item}" for item in evidence)
        keywords_str = (
            ", ".join(expected_keywords) if expected_keywords else "none specified"
        )
        return self._compile_prompt(
            GROUNDEDNESS_EVALUATION_PROMPT,
            {
                "evidence_text": evidence_text,
                "answer": answer,
                "keywords_text": keywords_str,
            },
        )


prompt_manager = PromptManager()
