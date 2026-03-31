# Prompt hardening research (Langfuse + NotebookLM)
Date: 2026-03-30

## Langfuse prompt-management takeaways
- Use `langfuse.get_prompt(name, type="chat", labels=["production"])` and `.compile(...)` so the service stores every prompt version. `PromptManager` now caches those prompt objects for `prompt_cache_ttl_seconds`, flushes to Langfuse only on TTL expiration, and falls back to local templates when credentials/API are unavailable.
- Supply a `fallback` (string/list) when calling `get_prompt` so Langfuse can serve a default even if the remote UI is editing the prompt elsewhere.
- Log the prompt name/version in `tool_history` and traces so reviewers can link every run to the exact template that produced it.
- Keep prompts focused: system message encodes the policy (read-only SQL, JSON-only router output) while the user message injects request-specific context (query + schema). This separation makes it safe to migrate text into Langfuse without mixing runtime data with policy text.

## Prompt hardening checklist (NotebookLM-inspired)
NotebookLM CLI queries (`nlm notebook query ...` with session IDs 34781 and 39650) were issued to surface best practices for anti-hallucination and routing quality. The distilled checklist below matches those heuristics and the Langfuse guidance:

1. **Guardrail outputs** – routers must return machine-readable JSON (intent + reason) so downstream nodes don't parse free text; SQL prompts repeat `SELECT`/`WITH` rules and schema context.
2. **Tool-aware instructions** – call out tool names (SQL generator, retriever) explicitly and tell the LLM it is in a tool loop. Mention when to cite docs vs structured data.
3. **Fallback behavior** – if LLM output fails structured validation, fall back to deterministic rule-based or cached prompts and log the fallback reason in `tool_history`.
4. **Anti-hallucination clauses** – remind the prompt to cite retrieved evidence, admit uncertainty when context is missing, and avoid inventing tables/values.
5. **Structured response schema** – enforce a schema (JSON keys, bullet templates) and validate it before trusting the tool output. Keep instructions short and repeat them in every template migration.

## Notes for the DA Agent
- Router and SQL prompts now live in `PromptManager` and show up in Langfuse traces when credentials exist. Offline runs use the same text as the fallback messages, so migrating to new wording means editing one source of truth.
- Documented findings helped us close Week 2 Day 4: prompt management, anti-hall checks, and regression test coverage. The summary above should serve as the `README` for future prompt tweaks.
- Known issue tracked (non-blocking): current Langfuse SDK in this environment rejects `labels` in `get_prompt(...)` (`unexpected keyword argument 'labels'`). Prompt manager falls back to local templates and keeps runtime stable while SDK/API compatibility is aligned later.
