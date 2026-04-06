# Plan: Full PostgreSQL Migration + Smart Memory

**Created**: 2026-04-06
**Status**: DRAFT
**Scope**: 3 phases — consolidate storage, add checkpointer, add smart memory

---

## Problem Statement

Project hiện tại có 3 vấn đề chính:

1. **SQLite rải rác**: 2 SQLite DB files (`conversation_memory.db`, `context_memory.db`) cho memory, 1 legacy migration (`result_store` SQLite), seed logic cho `analytics.db`. Docker volume `agent_data` chỉ share SQLite files.
2. **Schema hỗn loạn**: `result_store` table (Postgres) + user-uploaded tables đều nằm trong `public` schema. Xung đột tên, khó cleanup.
3. **Memory chưa thông minh**: Chỉ CRUD turns, không có semantic search, không có fact extraction. Qdrant dependency optional nhưng chưa dùng.

## Goal

- **1 database** (PostgreSQL) cho tất cả: user data, conversation memory, checkpoints, result store
- **Schema isolation**: `user_data` cho uploaded tables, `agent` cho internal state, `public` giữ nguyên cho extensions
- **3-layer smart memory**: Working (recent turns) + Episodic (pgvector similarity) + Semantic (extracted facts)
- **Clean story**: Xóa hết SQLite, xóa Qdrant dependency, xóa legacy migration

---

## Phase 1: Full PostgreSQL Consolidation

**Mục tiêu**: Migrate tất cả SQLite stores sang PostgreSQL, tách schema user data.

### 1.1 Tạo schema isolation trong PostgreSQL

**File mới**: `data/migrations/002_create_schemas.sql`

```sql
CREATE SCHEMA IF NOT EXISTS agent;
CREATE SCHEMA IF NOT EXISTS user_data;
```

**Sửa file**: `data/migrations/002_create_schemas.py` (migration runner)

- Tạo migration script chạy `002_create_schemas.sql`
- Set `search_path` cho agent connection: `agent, public`

### 1.2 Migrate ConversationMemoryStore → PostgreSQL

**File sửa**: `app/memory/conversation_store.py`

Hiện tại (SQLite):
```python
self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
# CREATE TABLE conversation_memory (...)
# INSERT INTO conversation_memory VALUES (?, ?, ...)
```

Sang PostgreSQL:
```python
def _get_connection(self):
    settings = load_settings()
    return psycopg.connect(settings.database_url)

# CREATE TABLE agent.conversation_memory (...)
# INSERT INTO agent.conversation_memory VALUES (%s, %s, ...)
```

Schema SQL:
```sql
CREATE TABLE IF NOT EXISTS agent.conversation_memory (
    id SERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    intent TEXT,
    sql_generated TEXT,
    result_summary TEXT,
    entities JSONB DEFAULT '[]',
    timestamp TIMESTAMPTZ NOT NULL,
    last_action_json JSONB,
    UNIQUE(thread_id, turn_number)
);

CREATE INDEX IF NOT EXISTS idx_conv_thread ON agent.conversation_memory(thread_id);
CREATE INDEX IF NOT EXISTS idx_conv_timestamp ON agent.conversation_memory(timestamp);

CREATE TABLE IF NOT EXISTS agent.conversation_summary (
    thread_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    turn_count INTEGER NOT NULL,
    last_updated TIMESTAMPTZ NOT NULL,
    key_entities JSONB DEFAULT '[]'
);
```

Key changes:
- `sqlite3.connect()` → `psycopg.connect()` (sync, consistent với existing codebase)
- `?` placeholders → `%s` placeholders
- `json.dumps(entities)` → `Jsonb(entities)` (native JSONB, query được)
- `json.loads(row["entities"])` → `row["entities"]` (psycopg tự parse JSONB)
- `AUTOINCREMENT` → `SERIAL`
- `TEXT` timestamp → `TIMESTAMPTZ`
- Singleton pattern giữ nguyên, chỉ đổi internal connection
- Thread-safety: psycopg connections là thread-safe khi dùng `with` pattern
- Mỗi operation lấy connection mới từ pool thay vì giữ persistent connection

### 1.3 Migrate ContextMemoryStore → PostgreSQL

**File sửa**: `app/memory/context_store.py`

Tương tự pattern:
```sql
CREATE TABLE IF NOT EXISTS agent.context_memory (
    id SERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    context_type TEXT NOT NULL,
    needs_semantic_context BOOLEAN NOT NULL,
    detected_intent JSONB NOT NULL,
    query TEXT NOT NULL,
    user_provided_context TEXT,
    source_files JSONB DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_context_thread ON agent.context_memory(thread_id);
CREATE INDEX IF NOT EXISTS idx_context_created ON agent.context_memory(created_at);
```

Key changes:
- `sqlite3.connect(db_path)` → `psycopg.connect(settings.database_url)` per operation
- `INTEGER` (boolean) → `BOOLEAN`
- `json.dumps/detect_intent` → `Jsonb(detected_intent)`
- Remove `_init_db()` riêng — dùng `_ensure_table_exists()` pattern như ResultStore

### 1.4 Move user-uploaded tables → `user_data` schema

**File sửa**: `app/tools/auto_register.py`

Hiện tại:
```python
cur.execute(f'DROP TABLE IF EXISTS {safe_table}')
cur.execute(pg_schema_sql)  # Creates in public schema
```

Sang:
```python
safe_table = f'user_data."{profile.table_name}"'
cur.execute(f'DROP TABLE IF EXISTS {safe_table}')
cur.execute(pg_schema_sql)  # Creates in user_data schema
```

**File sửa**: `app/tools/get_schema.py` — update schema introspection để query `user_data` schema
**File sửa**: `app/tools/query_sql.py` — update search_path hoặc prefix tables
**File sửa**: `data/seeds/create_seed_db.py` — seed vào `user_data` schema thay vì `public`

### 1.5 Update result_store → `agent` schema

**File sửa**: `app/tools/result_store.py`

Hiện tại table tạo trong `public`. Đổi sang:
```sql
CREATE TABLE IF NOT EXISTS agent.result_store (...)
```

### 1.6 Cleanup SQLite references

**Xóa/Sửa các files**:
- `data/migrations/001_create_result_store.py` — xóa (legacy SQLite migration, result_store đã chuyển sang Postgres)
- `backend/main.py:79` — remove `analytics.db` seed logic (đã dùng Postgres seed)
- `backend/main.py:54` — remove `get_conversation_memory_store()` pre-warm (sẽ pre-warm Postgres version)
- `app/tools/query_sql.py` — giữ `_query_sqlite()` cho eval/Spider (tách riêng), nhưng default path = None
- `tests/conftest.py:312` — update `analytics_db_path` fixture
- `docker-compose.yml` — remove `agent_data` volume comment về SQLite files

**Giữ lại SQLite chỉ cho**:
- `app/tools/query_sql.py:_query_sqlite()` — dùng cho Spider evaluation DBs (không liên quan production)
- `evals/` test cases — vẫn dùng SQLite DB files cho benchmark

### 1.7 Update tests

**File sửa**: `tests/test_v3_memory.py` — update fixtures dùng Postgres test DB thay vì SQLite
**File sửa**: `tests/conftest.py` — thêm Postgres test fixtures

### 1.8 Update documentation

- `CLAUDE.md` — remove SQLite references, update architecture diagram
- `docs/_tech_specs/01_state_model.md` — update state persistence docs
- `docs/RUNBOOK.md` — remove SQLite backup/restore instructions
- `docker-compose.yml` — simplify volumes, remove `agent_data` SQLite volume

---

## Phase 2: LangGraph Checkpointer + Store

**Mục tiêu**: Dùng `langgraph-checkpoint-postgres` để persist graph state, `langgraph-store-postgres` cho key-value memory.

### 2.1 Add dependencies

**File sửa**: `pyproject.toml`

```toml
dependencies = [
    # ... existing ...
    "langgraph-checkpoint-postgres>=2.0.0",
    "langgraph-store-postgres>=0.1.0",
]
```

Run: `uv add langgraph-checkpoint-postgres langgraph-store-postgres`

### 2.2 Create PostgresStore + Checkpointer factory

**File mới**: `app/memory/pg_stores.py`

```python
from __future__ import annotations

from functools import lru_cache
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore
from app.config import load_settings

@lru_cache(maxsize=1)
def get_checkpointer() -> PostgresSaver:
    settings = load_settings()
    checkpointer = PostgresSaver.from_conn_string(settings.database_url)
    checkpointer.setup()  # Creates checkpoint tables once
    return checkpointer

@lru_cache(maxsize=1)
def get_store() -> PostgresStore:
    settings = load_settings()
    store = PostgresStore.from_conn_string(settings.database_url)
    store.setup()  # Creates store tables once
    return store
```

### 2.3 Wire checkpointer vào graph

**File sửa**: `app/graph/graph.py`

Hiện tại:
```python
from langgraph.checkpoint.memory import InMemorySaver
# ...
return builder.compile(checkpointer=checkpointer or InMemorySaver())
```

Sang:
```python
from app.memory.pg_stores import get_checkpointer
# ...
return builder.compile(checkpointer=checkpointer or get_checkpointer())
```

Benefits:
- Graph state tự động persist sau mỗi node
- Resume-after-crash: nếu process crash mid-execution, graph resume từ checkpoint cuối
- Time-travel debugging: replay graph execution từ bất kỳ checkpoint nào
- Interrupt support: `clarify_question_node` dùng LangGraph interrupt native

### 2.4 Use PostgresStore cho semantic memory

**File sửa**: `app/graph/nodes.py` — `inject_session_context` node

Thêm semantic memory retrieval:
```python
from app.memory.pg_stores import get_store

store = get_store()
# Search relevant memories for this user/thread
memories = store.search(
    ("memories", thread_id),
    query=state.get("user_query", ""),
)
```

### 2.5 Update API layer để dùng checkpointer

**File sửa**: `backend/services/agent_service.py`

Graph invocation cần pass `config` với `thread_id`:
```python
config = {"configurable": {"thread_id": thread_id}}
result = graph.invoke(input_state, config)
```

---

## Phase 3: pgvector Smart Memory

**Mục tiêu**: Thêm vector similarity search, fact extraction, 3-layer memory retrieval.

### 3.1 Add pgvector extension

**File sửa**: `docker-compose.yml`

```yaml
postgres:
  image: pgvector/pgvector:pg15  # Thay postgres:15-alpine
```

**Migration mới**: `data/migrations/003_enable_pgvector.sql`

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

**Add dependency**: `pyproject.toml`

```toml
"pgvector>=0.3.0",
```

### 3.2 Add embedding columns

**Migration mới**: `data/migrations/004_add_embeddings.sql`

```sql
-- Add embedding to conversation memory
ALTER TABLE agent.conversation_memory
    ADD COLUMN IF NOT EXISTS embedding vector(384);

CREATE INDEX IF NOT EXISTS idx_conv_embedding
    ON agent.conversation_memory USING hnsw (embedding vector_cosine_ops);

-- Create extracted facts table
CREATE TABLE IF NOT EXISTS agent.extracted_facts (
    id SERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    fact_type TEXT NOT NULL DEFAULT 'other',
        -- types: preference, metric_definition, business_rule, data_source, other
    source_turn_id INTEGER REFERENCES agent.conversation_memory(id),
    confidence REAL DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    embedding vector(384)
);

CREATE INDEX IF NOT EXISTS idx_facts_embedding
    ON agent.extracted_facts USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_facts_thread
    ON agent.extracted_facts(thread_id);
```

### 3.3 Create embedding service

**File mới**: `app/memory/embeddings.py`

```python
from __future__ import annotations
from functools import lru_cache

# Reuse existing sentence-transformers model
@lru_cache(maxsize=1)
def get_embedding_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

def embed_text(text: str) -> list[float]:
    model = get_embedding_model()
    return model.encode(text).tolist()
```

Note: Model `all-MiniLM-L6-v2` (384 dims) nhẹ, chạy local, không cần API call. Đã có trong dependencies qua `sentence-transformers`.

### 3.4 Update compact_and_save_memory node

**File sửa**: `app/graph/nodes.py` — `compact_and_save_memory()`

Thêm embedding khi save turn:
```python
from app.memory.embeddings import embed_text

# After saving turn to conversation_memory
embedding = embed_text(user_query)
conn.execute(
    "UPDATE agent.conversation_memory SET embedding = %s WHERE id = %s",
    (str(embedding), turn_id),
)
```

### 3.5 Create fact extraction service

**File mới**: `app/memory/fact_extractor.py`

```python
from __future__ import annotations
import json
from app.llm import LLMClient

FACT_EXTRACTION_PROMPT = """Extract structured facts from this conversation turn.
Return JSON array of facts, each with: subject, predicate, object, fact_type, confidence.

Fact types: preference, metric_definition, business_rule, data_source, other

Example output:
[{"subject": "user", "predicate": "prefers", "object": "SQL mode", "fact_type": "preference", "confidence": 0.9}]

If no facts found, return empty array: []

User message: {user_message}
Assistant response: {assistant_response}
"""

def extract_facts(user_msg: str, assistant_msg: str) -> list[dict]:
    """Extract facts from a conversation turn using LLM."""
    llm = LLMClient.from_env()
    prompt = FACT_EXTRACTION_PROMPT.format(
        user_message=user_msg,
        assistant_response=assistant_msg,
    )
    response = llm.chat([{"role": "user", "content": prompt}])
    # Parse JSON array from response
    facts = _parse_json_array(response)
    return facts
```

### 3.6 Update inject_session_context — 3-layer retrieval

**File sửa**: `app/graph/nodes.py` — `inject_session_context()`

```python
def inject_session_context(state: AgentState) -> AgentState:
    thread_id = state.get("thread_id")
    user_query = state.get("user_query", "")

    # Layer 1: Working Memory — recent N turns (SQL pagination)
    recent_turns = conv_store.get_recent_turns(thread_id, limit=10)

    # Layer 2: Episodic Memory — semantic similarity (pgvector)
    semantically_relevant = conv_store.search_similar_turns(
        thread_id, user_query, limit=5
    )

    # Layer 3: Semantic Memory — extracted facts
    facts = fact_store.get_relevant_facts(
        thread_id, user_query, limit=5
    )

    # Assemble context
    context_parts = []
    if summary:
        context_parts.append(f"[Summary]\n{summary.summary}")
    if recent_turns:
        context_parts.append(format_turns(recent_turns))
    if semantically_relevant:
        context_parts.append(format_similar(semantically_relevant))
    if facts:
        context_parts.append(format_facts(facts))

    return {"session_context": "\n\n".join(context_parts), ...}
```

### 3.7 Remove Qdrant dependency

**Xóa file**: `app/memory/qdrant_client.py`
**Sửa file**: `backend/main.py` — remove Qdrant pre-warm logic (lines 63-76)
**Sửa file**: `pyproject.toml` — remove `qdrant-client`, `sentence-transformers` đã có

---

## Files Changed Summary

### Phase 1 — Full PostgreSQL Consolidation
| Action | File | Change |
|--------|------|--------|
| NEW | `data/migrations/002_create_schemas.py` | Schema isolation migration |
| EDIT | `app/memory/conversation_store.py` | SQLite → PostgreSQL |
| EDIT | `app/memory/context_store.py` | SQLite → PostgreSQL |
| EDIT | `app/tools/auto_register.py` | Tables → `user_data` schema |
| EDIT | `app/tools/get_schema.py` | Query `user_data` schema |
| EDIT | `app/tools/result_store.py` | Table → `agent` schema |
| EDIT | `data/seeds/create_seed_db.py` | Seed → `user_data` schema |
| EDIT | `backend/main.py` | Remove SQLite seed/pre-warm |
| EDIT | `docker-compose.yml` | Remove SQLite volume refs |
| DELETE | `data/migrations/001_create_result_store.py` | Legacy SQLite migration |
| EDIT | `tests/conftest.py` | Update fixtures |
| EDIT | `tests/test_v3_memory.py` | Update for PostgreSQL |

### Phase 2 — LangGraph Checkpointer + Store
| Action | File | Change |
|--------|------|--------|
| EDIT | `pyproject.toml` | Add checkpoint-postgres, store-postgres |
| NEW | `app/memory/pg_stores.py` | Checkpointer + Store factory |
| EDIT | `app/graph/graph.py` | Wire PostgresSaver checkpointer |
| EDIT | `app/graph/nodes.py` | Use PostgresStore for memory |
| EDIT | `backend/services/agent_service.py` | Pass thread_id config |

### Phase 3 — pgvector Smart Memory
| Action | File | Change |
|--------|------|--------|
| EDIT | `docker-compose.yml` | `pgvector/pgvector:pg15` image |
| NEW | `data/migrations/003_enable_pgvector.sql` | Enable pgvector |
| NEW | `data/migrations/004_add_embeddings.sql` | Add embedding columns + facts table |
| EDIT | `pyproject.toml` | Add `pgvector` |
| NEW | `app/memory/embeddings.py` | Embedding service |
| NEW | `app/memory/fact_extractor.py` | LLM fact extraction |
| EDIT | `app/graph/nodes.py` | 3-layer retrieval in inject_session_context |
| DELETE | `app/memory/qdrant_client.py` | Replace with pgvector |

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| psycopg connection pool exhaustion under load | MEDIUM | Use connection pool (psycopg_pool). Currently project is single-user, low risk |
| pgvector extension not available in Docker | LOW | Use `pgvector/pgvector:pg15` image which bundles it |
| Migration breaks existing conversation history | HIGH | Write migration script to copy SQLite → Postgres before cutover |
| Fact extraction LLM cost | MEDIUM | Use cheap model (gpt-4o-mini), only extract from assistant turns |
| Schema migration breaks SQL tools | MEDIUM | Test all query paths after schema change, update search_path |

## Implementation Order

```
Phase 1 (foundational, do first):
  1.1 → 1.2 → 1.3 → 1.5 → 1.4 → 1.6 → 1.7 → 1.8

Phase 2 (depends on Phase 1):
  2.1 → 2.2 → 2.3 → 2.4 → 2.5

Phase 3 (depends on Phase 1, independent from Phase 2):
  3.1 → 3.2 → 3.3 → 3.4 → 3.5 → 3.6 → 3.7
```

Phase 1 và Phase 2 nên làm tuần tự (Phase 2 cần Phase 1).
Phase 3 có thể làm song song với Phase 2 nếu cần.
