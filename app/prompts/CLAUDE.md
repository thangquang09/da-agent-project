# Prompts Documentation

All LLM prompts are centralized in this folder. Each prompt is defined as a `PromptDefinition` dataclass with templating support for variables.

## Prompt Files

| File | Prompt Name | Purpose | Status |
|------|-------------|---------|--------|
| `task_grounder.py` | `TASK_GROUNDER_PROMPT_DEFINITION` | Classifies user query into structured TaskProfile (5 dimensions) | **Active** |
| `leader.py` | `LEADER_AGENT_PROMPT_DEFINITION` | Supervisor tool routing with diagnostic reasoning | **Active** |
| `sql_worker.py` | `SQL_WORKER_GENERATION_PROMPT` | SQL expert prompt for worker nodes | **Active** |
| `sql_worker.py` | `SQL_WORKER_SELF_CORRECTION_PROMPT_DEFINITION` | Self-corrects SQL with error context | **Active** |
| `analysis.py` | `ANALYSIS_PROMPT_DEFINITION` | Analyzes SQL query results | **Active** |
| `synthesis.py` | `SYNTHESIS_PROMPT_DEFINITION` | Synthesizes natural language from SQL results | **Active** |
| `classifier.py` | `RETRIEVAL_TYPE_CLASSIFIER_PROMPT` | Classifies retrieval type: metric_definition vs business_context | **Active** |
| `fallback.py` | `FALLBACK_ASSISTANT_PROMPT` | Handles unknown/unclassifiable queries | **Active** |
| `chitchat_response.py` | `CHITCHAT_RESPONSE_PROMPT_DEFINITION` | Generates friendly chitchat responses | **Active** |
| `auto_context.py` | `AUTO_CONTEXT_PROMPT_DEFINITION` | Auto-generates business context from schema + sample rows | **Active** |
| `decomposition.py` | `TASK_DECOMPOSITION_PROMPT` | Decomposes queries into parallelizable sub-tasks | **Active** |
| `visualization.py` | `VISUALIZATION_CODE_GENERATION_PROMPT` | Generates Python visualization code | **Active** |
| `continuity.py` | `CONTINUITY_DETECTION_PROMPT_DEFINITION` | Detects implicit follow-up queries | **Active** |
| `evaluation.py` | `GROUNDEDNESS_EVALUATION_PROMPT` | Evaluates answer groundedness | **Active** |
| `report_data_profiler.py` | `REPORT_DATA_PROFILER_PROMPT_DEFINITION` | Analyzes sample rows + column stats for domain summary | **Active** |
| `report_planner.py` | `REPORT_PLANNER_PROMPT_DEFINITION` | Plans multi-section report structure | **Active** |
| `report_insight.py` | `REPORT_INSIGHT_PROMPT_DEFINITION` | Writes grounded section insights from stats + chart | **Active** |
| `report_writer.py` | `REPORT_WRITER_PROMPT_DEFINITION` | Assembles full Markdown report from insights | **Active** |
| `report_critic.py` | `REPORT_CRITIC_PROMPT_DEFINITION` | Reviews report for unsupported claims | **Active** |
| `router.py` | `ROUTER_PROMPT_DEFINITION` | Legacy intent router (superseded by task_grounder) | **Deprecated** |
| `context_detection.py` | `CONTEXT_DETECTION_PROMPT_DEFINITION` | Context type detection (unused in graph) | **Deprecated** |

## Usage

Import via `PromptManager` for automatic variable substitution and Langfuse integration:

```python
from app.prompts import prompt_manager

messages = prompt_manager.task_grounder_messages(query="What is DAU?", session_context="")
messages = prompt_manager.leader_agent_messages(query="Top 5 products?", xml_database_context="...")
```

Or import definitions directly:

```python
from app.prompts import TASK_GROUNDER_PROMPT_DEFINITION
```

## Template Syntax

Prompts use `{{variable}}` syntax for variable substitution. Conditional blocks use `{{#if var}}...{{/if}}`.

## Langfuse Integration

`PromptManager` fetches prompts from Langfuse when available, with local fallbacks. Set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` environment variables to enable.

## Report Prompt Roles

Report generation is an 8-node pipeline using LangGraph `Send()` for per-section fan-out:

1. `profiler_sampler` — runs `SELECT * FROM table ORDER BY RANDOM() LIMIT 100` + column stats. Pure SQL, no LLM.
2. `profiler_analyzer` — LLM reads schema + sample data + business_context to produce domain summary + suggested sections.
3. `report_planner` — builds `ReportPlan` with `domain_context`.
4. `section_pipeline` (via `Send()` fan-out) — each section independently: SQL → sandbox → insight generation.
5. `sections_sort` — reassembles sections in planner order.
6. `report_writer` — synthesizes Executive Summary + Recommendations from grounded insights.
7. `report_critic` — validates grounding. Max 2 revisions.
8. `report_finalize` — packages final markdown + section payloads.

## Design Principles

1. **Language-agnostic**: All prompts written in English with explicit instructions to match user language.
2. **Structured output**: Classification prompts return JSON with defined schemas.
3. **Groundedness**: Report pipeline enforces numeric claims must come from `computed_stats`.
4. **Convention**: All prompts use `PromptDefinition` dataclass (not custom classes).
