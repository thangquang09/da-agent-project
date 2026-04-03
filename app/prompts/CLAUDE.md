# Prompts Documentation

All LLM prompts are centralized in this folder. Each prompt is defined as a `PromptDefinition` dataclass with templating support for variables.

## Prompt Files

| File | Prompt Name | Purpose |
|------|-------------|---------|
| `router.py` | `ROUTER_PROMPT_DEFINITION` | Classifies user intent into sql/rag/mixed/unknown |
| `sql.py` | `SQL_PROMPT_DEFINITION` | Generates SQL queries from user questions |
| `sql.py` | `SQL_SELF_CORRECTION_PROMPT_DEFINITION` | Self-corrects SQL with error context |
| `sql_worker.py` | `SQL_WORKER_GENERATION_PROMPT` | SQL expert prompt for worker nodes |
| `analysis.py` | `ANALYSIS_PROMPT_DEFINITION` | Analyzes SQL query results |
| `synthesis.py` | `SYNTHESIS_PROMPT_DEFINITION` | Synthesizes natural language from SQL results |
| `context_detection.py` | `CONTEXT_DETECTION_PROMPT_DEFINITION` | Detects context type for RAG retrieval |
| `classifier.py` | `RETRIEVAL_TYPE_CLASSIFIER_PROMPT` | Classifies retrieval type: metric_definition vs business_context |
| `fallback.py` | `FALLBACK_ASSISTANT_PROMPT` | Handles unknown/unclassifiable queries |
| `decomposition.py` | `TASK_DECOMPOSITION_PROMPT` | Decomposes queries into parallelizable sub-tasks |
| `visualization.py` | `VISUALIZATION_CODE_GENERATION_PROMPT` | Generates Python visualization code |
| `continuity.py` | `CONTINUITY_DETECTION_PROMPT_DEFINITION` | Detects implicit follow-up queries |
| `evaluation.py` | `GROUNDEDNESS_EVALUATION_PROMPT` | Evaluates answer groundedness |

## Usage

Import via `PromptManager` for automatic variable substitution and Langfuse integration:

```python
from app.prompts import prompt_manager

# Get compiled messages with variables substituted
messages = prompt_manager.router_messages(query="What is DAU?", session_context="")
```

Or import definitions directly for custom handling:

```python
from app.prompts import ROUTER_PROMPT_DEFINITION
```

## Template Syntax

Prompts use `{{variable}}` syntax for variable substitution. Conditional blocks use `{{#if var}}...{{/if}}`.

## Langfuse Integration

`PromptManager` fetches prompts from Langfuse when available, with local fallbacks. Set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` environment variables to enable.
