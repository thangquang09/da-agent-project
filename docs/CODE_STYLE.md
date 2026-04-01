# Code Style Guidelines — DA Agent Lab

Tài liệu này chứa coding conventions cho project. Được tham chiếu từ `CLAUDE.md`.

---

## Imports
- Always use `from __future__ import annotations` as the first import.
- Group imports in order: stdlib → third-party → local/project.
- Use explicit imports (no `import *` except in `__init__.py`).

```python
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import load_settings
from app.logger import logger
```

---

## Type Hints
- Use modern Python type hints with `|` for unions (e.g., `Path | None`).
- Use `TypedDict` for structured dicts (state, payloads).
- Use `Literal` for enum-like string constants (intent, confidence).
- Use `Annotated[..., operator.add]` for LangGraph state fields that accumulate.

```python
Intent = Literal["sql", "rag", "mixed", "unknown"]

class AgentState(TypedDict, total=False):
    user_query: str
    intent: Intent
    tool_history: Annotated[list[dict[str, Any]], operator.add]
```

---

## Naming Conventions

| Category | Convention | Example |
|----------|-----------|---------|
| Files | snake_case | `get_schema.py`, `query_sql.py` |
| Classes | PascalCase | `SQLValidationResult`, `AgentState` |
| Functions/methods | snake_case | `validate_sql`, `get_schema_overview` |
| Constants | SCREAMING_SNAKE_CASE | `FORBIDDEN_SQL_PATTERNS` |
| Type variables | PascalCase | `Intent`, `Confidence` |
| Private helpers | `_`prefix | `_default_db_path` |

---

## Data Classes
- Use `@dataclass(frozen=True)` for immutable data structures (configs, validation results).

```python
@dataclass(frozen=True)
class SQLValidationResult:
    is_valid: bool
    sanitized_sql: str
    reasons: list[str]
    detected_tables: list[str]
```

---

## Error Handling
- Use specific exception types; avoid bare `except:`.
- Let exceptions propagate for unrecoverable errors.
- Log errors with `logger.exception()` at the boundary where they are caught.
- Return validation results with `is_valid=False` and `reasons` list instead of raising for expected validation failures.

---

## SQL Safety
- All SQL operations must go through `validate_sql` before execution.
- **Never allow**: INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, REPLACE.
- Only allow SELECT and CTE queries.
- Always use parameterized queries via sqlite3; never interpolate user input directly.

---

## Logging
- Use `loguru` only. Do not add `logging` module handlers unless there is a hard external integration need.
- Use structured logging with named placeholders: `logger.info("msg {key}", key=value)`.
- Log at component boundaries (router, tools, SQL validation, execution, retrieval, synthesis).
- Never log secrets (`LLM_API_KEY`, raw auth headers, tokens).

| Level | Use for |
|-------|---------|
| `info` | Normal flow events, start/completion |
| `warning` | Recoverable issues, degraded mode |
| `error`/`exception` | Failed operations |

---

## Testing
- Use `pytest` with fixtures from `conftest.py`.
- Test file naming: `test_<module_name>.py`.
- Use `monkeypatch` for mocking LLM clients and environment variables.

```python
class _DummyRouterClient:
    def chat_completion(self, **kwargs):  # noqa: ANN003
        return {"choices": [{"message": {"content": '{"intent":"sql"}'}}]}
```

---

## State Management
- Keep critical artifacts explicit in state: `intent`, `generated_sql`, `retrieved_context`, `tool_history`, `errors`.
- Use `Annotated[list, operator.add]` for fields that accumulate across nodes.
- Never hide intermediate values; they are needed for tracing and evaluation.

---

## Module Organization
- Each tool should have explicit input/output schemas.
- Keep business logic in tools, not buried in prompts.
- Use `__init__.py` to expose public API with `__all__`.
- Place MCP server in separate adapter layer (`mcp_server/`).
