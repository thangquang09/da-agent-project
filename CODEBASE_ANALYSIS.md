# DA Agent Project - Complete Codebase Analysis

## QUICK EXECUTIVE SUMMARY

**Project**: LangGraph-based Data Analyst Agent
**Main Entry Point**: `app.main.run_query()` (orchestrates graph execution)
**UI**: Monolithic Streamlit app (`streamlit_app.py`)
**State Machine**: LangGraph with 2 versions (v1=linear, v2=plan-and-execute)
**Key Innovation**: Plan-and-Execute architecture with parallel SQL workers
**Memory**: SQLite-backed conversation & context stores (NEW - Sprint 1)
**Observability**: JSONL traces + Langfuse integration

---

## 1. DIRECTORY STRUCTURE (Key Files)

```
app/
├── main.py                    # Entry: run_query(user_query, thread_id, ...)
├── config.py                  # Settings, models, environment
├── graph/
│   ├── state.py              # AgentState, TaskState, AnswerPayload (TypedDicts)
│   ├── graph.py              # build_sql_v1_graph() & build_sql_v2_graph()
│   ├── nodes.py              # 14 node functions (detect, route, generate, execute, etc.)
│   ├── edges.py              # Routing logic (conditional edges)
│   ├── sql_worker_graph.py   # Subgraph for parallel SQL execution
│   └── visualization_node.py # E2B sandboxed chart generation
├── tools/
│   ├── get_schema.py         # DB schema retrieval
│   ├── query_sql.py          # Safe SQL execution
│   ├── validate_sql.py       # SQL safety checks
│   ├── retrieve_*            # RAG tools
│   ├── csv_*                 # CSV validation/profiling/import
│   └── visualization.py      # Viz data prep
├── memory/
│   ├── conversation_store.py # Conversation turns + summaries (SQLite)
│   ├── context_store.py      # Context detection history
│   └── qdrant_client.py      # Semantic memory (WIP)
├── observability/
│   ├── tracer.py             # RunTracer (JSONL + Langfuse)
│   └── schemas.py            # Trace record types
└── llm/
    └── client.py             # OpenAI-compatible API client

mcp_server/
├── server.py                 # FastMCP with 7 exposed tools

streamlit_app.py              # Monolithic UI (session state, chat, rendering)

evals/
├── runner.py                 # Eval orchestrator
├── metrics/                  # Exact match, LLM judge, official Spider
└── case_contracts.py         # Test case execution

pyproject.toml                # Dependencies (LangGraph, Langfuse, etc.)
```

---

## 2. DATA FLOW: Query → Graph → Response

### Request Entry (streamlit_app.py)
```
User submits query
    → st.chat_input() / st.button(sample)
    → _append_user_query() [append to pending_queries queue]
    → st.rerun()

Queue processing (on each rerun):
    → _schedule_next_if_needed() [dequeue if not processing]
    → _run_current_query_if_needed() [execute if processing]
        → run_agent(query, thread_id, user_context, files)
            → app.main.run_query()
```

### Core Execution (app/main.py)
```python
def run_query(
    user_query: str,
    thread_id: str | None = None,
    version: str = "v2",
    recursion_limit: int = 25,
    ...
) -> dict:
    
    1. Select graph builder: GRAPH_REGISTRY[version]
    2. Create RunTracer(run_id, thread_id, query)
    3. Build graph input dict
    4. Execute: graph.invoke(graph_input, config)
    5. Extract payload & augment with metadata
    6. tracer.finish(payload)
    7. Return payload
```

### Graph Execution (LangGraph - V2 Default)

**V1 (Linear Path)**:
```
detect_context 
  → [has files?] → process_files
      → inject_session_context
          → route_intent
              ├→ SQL: get_schema → generate_sql → validate → execute → analyze
              ├→ RAG: retrieve_context
              └→ Unknown: synthesize
          → synthesize_answer
          → compact_and_save_memory → END
```

**V2 (Plan-and-Execute via Send API)**:
```
detect_context 
  → process_files
      → inject_session_context [fetches recent turns from conversation_store]
          → route_intent
              ├→ SQL/Mixed: task_planner
              │   ├→ Send(sql_worker, task1) [PARALLEL]
              │   └→ Send(sql_worker, task2) [PARALLEL]
              │       ├→ Each worker: get_schema → generate → validate → execute
              │       └→ aggregate_results [Fan-in]
              │
              ├→ RAG: retrieve_context
              │
              └→ Unknown: synthesize
              
          → synthesize_answer
          → compact_and_save_memory [saves turn to conversation_store]
              → END
```

### Response Structure
```python
{
    # Execution metadata
    "run_id": "run-xyz",
    "thread_id": "abc-def",  # Links to memory
    "intent": "sql" | "rag" | "mixed" | "unknown",
    "context_type": "default" | "user_provided" | "csv_auto" | "mixed",
    
    # Main answer
    "answer": "DAU trong 7 ngày gần đây ...",
    "confidence": "high" | "medium" | "low",
    "evidence": ["DAU 2026-03-31: 11,200", ...],
    
    # Tools & execution trace
    "used_tools": ["get_schema", "generate_sql", "execute_sql", ...],
    "generated_sql": "SELECT date, dau FROM ...",
    "tool_history": [
        {"tool": "get_schema", "latency_ms": 45, ...},
        {"tool": "generate_sql", "tokens": 850, "cost": 0.0045, ...},
    ],
    
    # Visualization
    "visualization": {
        "success": True,
        "image_data": "iVBORw0KGgo...",  # base64 PNG
        "execution_time_ms": 1234,
        "error": None,
    },
    
    # Observability
    "step_count": 7,
    "total_token_usage": 1500,
    "total_cost_usd": 0.0085,
    "errors": [],
    "error_categories": [],
}
```

---

## 3. KEY ARCHITECTURAL COMPONENTS

### 3.1 State Model (app/graph/state.py)

Core TypedDicts:
- **AgentState** - The full conversation state (used internally)
  - User inputs: user_query, user_semantic_context, uploaded_files
  - Routing: intent, context_type, detected_intent
  - SQL execution: generated_sql, validated_sql, sql_result
  - Plan-Execute: task_plan, task_results (fan-in via operator.add), execution_mode
  - Memory: thread_id, session_context, conversation_turn, file_cache
  - Observability: tool_history, errors, run_id, step_count
  - Output: final_answer, final_payload, visualization

- **TaskState** - Individual task for parallel execution
  - task_id, task_type, query, generated_sql, sql_result, status, error
  - requires_visualization, visualization data

- **AnswerPayload** - Final structured response
  - answer, evidence, confidence, used_tools, generated_sql, visualization

- **GraphInputState** - What users pass in
  - user_query, target_db_path, user_semantic_context, uploaded_files, thread_id

- **GraphOutputState** - What graph returns to caller
  - final_answer, final_payload, intent, errors, step_count, run_id

### 3.2 Session Memory (NEW - Sprint 1)

**Files**: `app/memory/conversation_store.py`, `app/memory/context_store.py`

**ConversationMemoryStore** (SQLite):
- Stores `ConversationTurn` objects: thread_id, turn_number, role, content, intent, sql_generated, result_summary, entities, timestamp
- Stores `ConversationSummary`: thread_level summary + key entities
- Accessed via `inject_session_context()` node
- Formatted and injected into LLM prompts for context

**Thread ID Scoping**:
- Streamlit passes `thread_id` (UUID) from session_state
- Memory lookups filtered by `thread_id`
- Enables multi-turn conversation context without cross-contamination

**Lifecycle**:
1. User submits query with `thread_id`
2. `inject_session_context()` fetches recent turns from DB
3. Format & inject into LLM system prompt
4. Agent executes with context awareness
5. `compact_and_save_memory()` saves new turn to DB (keep last 50 per thread)

### 3.3 Observability (app/observability/tracer.py)

**RunTracer** - One per graph execution:
- Records `RunTraceRecord`: run_id, thread_id, intent, status, latency_ms, total_token_usage, error_categories
- Records `NodeTraceRecord` per node: node_name, attempt, latency_ms, input_summary, output_summary, error_category

**Outputs**:
- JSONL file: `evals/reports/traces.jsonl` (local analytics)
- Langfuse: Remote dashboard if `ENABLE_LANGFUSE=true`

**Error Taxonomy**:
- ROUTING_ERROR, SQL_GENERATION_ERROR, SQL_VALIDATION_ERROR, SQL_EXECUTION_ERROR
- RAG_RETRIEVAL_ERROR, SYNTHESIS_ERROR, CSV_PROCESSING_ERROR, VISUALIZATION_ERROR
- STEP_LIMIT_REACHED, RAG_IRRELEVANT_CONTEXT, EMPTY_RESULT

### 3.4 LangGraph Architecture (V1 vs V2)

**V1 (build_sql_v1_graph)**:
- Linear execution with self-correction loops
- SQL path: get_schema → generate → validate → execute → analyze → retrieve_context → synthesize
- Retry logic: invalid SQL re-enters generate_sql (up to 2 attempts)
- Simpler but slower for complex queries

**V2 (build_sql_v2_graph)** ← DEFAULT:
- Introduces `task_planner` node (LLM decomposes query into subtasks)
- Uses LangGraph `Send()` API for parallel worker dispatch
- Each worker is isolated SQL subgraph (get_schema → generate → validate → execute → viz)
- `aggregate_results` fan-in combines findings
- Supports parallelism: multiple SQL queries run concurrently

**Graph selection**: `run_query(..., version="v2")` defaults to V2

---

## 4. TOOLS & CAPABILITIES

### SQL Tools
- `get_schema(db_path)` - Fetch DB schema (abbreviated or full)
- `query_sql(sql, row_limit, db_path)` - Execute validated SELECT (max 200 rows)
- `validate_sql(sql)` - Deterministic safety: only SELECT/CTE; block DDL/DML

### RAG Tools
- `retrieve_metric_definition(query, top_k=4)` - Vector search over metrics
- `retrieve_business_context(query, top_k=4)` - Vector search over docs
- `dataset_context(db_path)` - Dataset-level metadata chunks

### File Tools
- `validate_csv(file_path)` - Check encoding, delimiter
- `profile_csv(file_path, ...)` - Column stats, type inference, row count
- `auto_register_csv(file_path, table_name, db_path)` - Register as SQLite table

### Utility
- `check_table_exists(table_name, db_path)` - Table existence check

**Exposed via MCP**: FastMCP server at `:8000/mcp` (7 tools)

---

## 5. HOW STREAMLIT CALLS THE AGENT

### Session Initialization
```python
def _init_state():
    st.session_state.setdefault("thread_id", str(uuid.uuid4()))  # ← KEY
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("pending_queries", [])
    st.session_state.setdefault("is_processing", False)
```

### Query Submission → Execution → Rendering
```
1. User types query + hits enter
   → st.chat_input() → _append_user_query() 
   → st.session_state["pending_queries"].append(query)
   → st.rerun()

2. Streamlit rerun cycle:
   
   _schedule_next_if_needed():
     if is_processing: return
     if pending_queries empty: return
     else: pop query, is_processing=True, st.rerun()
   
   _run_current_query_if_needed():
     if not is_processing: return
     with st.chat_message("assistant"):
       result = run_agent(
           user_query=query,
           thread_id=st.session_state["thread_id"],  # ← Memory scoping!
           user_semantic_context=...,
           uploaded_files=...,
           ...
       )
       chat_history[idx]["result"] = result
       is_processing = False
       st.rerun()

3. Next rerun renders result:
   for message in st.session_state["chat_history"]:
       with st.chat_message(role):
           _render_result(result)
```

### Thread ID Persistence
- Created once on first Streamlit load: `uuid.uuid4()`
- Persists in `st.session_state` across reruns
- Reset on "New Conversation" button
- Passed to `graph.invoke()` for memory lookups
- Enables multi-turn conversation context

---

## 6. MEMORY & CONTEXT FLOW

### Per-Turn Memory Injection
```
detect_context_type() 
  ↓
process_uploaded_files()  [if CSV]
  ↓
inject_session_context()  ← KEY
  │
  ├─ conversation_store.get_recent_turns(thread_id, limit=10)
  ├─ Format: "Previous context: [Q: ..., A: ..., Q: ..., A: ...]"
  └─ state.session_context = formatted_string
      [Passed to LLM system prompt]
      
  → route_intent()
      [LLM can reference past queries/answers]
```

### Turn Saving
```
After synthesize_answer()
  ↓
compact_and_save_memory()
  │
  ├─ ConversationTurn(
  │     thread_id=thread_id,
  │     turn_number=next_turn,
  │     role="user",
  │     content=user_query,
  │     intent=intent,  # "sql" | "rag" | "mixed" | "unknown"
  │     sql_generated=generated_sql,
  │     result_summary=final_answer,
  │     entities=[extracted],
  │     timestamp=now()
  │  )
  │
  ├─ conversation_store.save_turn(turn)
  ├─ Prune old turns (keep last 50 per thread)
  └─ Update conversation_summary
```

### CSV File Caching
```
process_uploaded_files()
  │
  for each file:
    ├─ file_hash = hash(file_data)  [SHA256]
    │
    ├─ if file_hash in state.file_cache:
    │   ├─ Skip (use cached metadata)
    │   └─ state.skipped_tables.append(table_name)
    │
    └─ else:
        ├─ validate_csv()
        ├─ profile_csv()
        ├─ auto_register_csv()
        └─ state.file_cache[file_hash] = {...metadata...}
```

---

## 7. RECENT IMPLEMENTATIONS (Sprint 1)

### Memory System (Conversation & Context Stores)
- `ConversationMemoryStore`: SQLite with persistent connection
- Stores turns, summaries, key entities per thread
- Thread-safe singleton pattern
- Integration: `inject_session_context()` → LLM prompt injection

### Evaluation Pipeline
- Test case execution framework (case_contracts.py)
- Metrics: routing_accuracy, sql_validity_rate, answer_format_validity, groundedness_pass_rate
- Quality gates: ≥0.90 for most metrics
- Official Spider eval integration

### LangGraph V2 with Plan-and-Execute
- `task_planner` node decomposes complex queries
- `Send()` API dispatches to parallel sql_worker subgraphs
- `aggregate_results` fan-in consolidates findings
- Self-correction loops inside each worker

### E2B Visualization
- LLM generates matplotlib/seaborn code
- E2B Sandbox executes isolated
- PNG base64-encoded in response
- Fallback template chart on failure

---

## 8. IMPORTANT FOR BACKEND API DESIGN

### What's Already in Place
1. **Decoupled entry point**: `app.main.run_query()` (UI-agnostic)
2. **Type-safe state**: AgentState TypedDict (Pydantic-ready)
3. **Shared memory**: SQLite stores (multi-instance compatible)
4. **Full tracing**: RunTracer writes to JSONL + Langfuse
5. **Error handling**: Structured errors list
6. **File handling**: Hash-based caching (deduplication)
7. **Session scoping**: thread_id parameter (multi-tenant ready)

### What Needs to be Added for API
1. **Request validation**: Pydantic models for /api/query endpoint
2. **Async execution**: Use `graph.ainvoke()` instead of blocking invoke()
3. **Job queuing**: Redis/RabbitMQ for long-running queries
4. **Authentication**: User → thread_id mapping, rate limits
5. **WebSocket/SSE**: Stream progress updates to client
6. **Result caching**: Cache identical queries (use run_id as key)
7. **Pagination**: Handle large result sets
8. **Status endpoint**: Poll query progress

### Suggested API Endpoints
```
POST   /api/v1/query                    # Submit query, get run_id
GET    /api/v1/runs/{run_id}            # Fetch completed result
GET    /api/v1/runs/{run_id}/status     # Poll status
WS     /api/v1/runs/{run_id}            # WebSocket for streaming
POST   /api/v1/sessions                 # Create new session (thread)
GET    /api/v1/sessions/{thread_id}/history  # Conversation history
POST   /api/v1/sessions/{thread_id}/context  # Save semantic context
```

---

## 9. KEY FILES SUMMARY

| File | Purpose | Key Classes/Functions |
|------|---------|----------------------|
| streamlit_app.py | UI layer | run_agent(), _render_result(), queue management |
| app/main.py | Orchestrator | run_query() [MAIN ENTRY POINT] |
| app/graph/state.py | Type definitions | AgentState, TaskState, AnswerPayload |
| app/graph/graph.py | Graph builder | build_sql_v1_graph(), build_sql_v2_graph() |
| app/graph/nodes.py | Node functions | 14 nodes (detect, route, execute, etc.) |
| app/graph/sql_worker_graph.py | Subgraph | Parallel SQL worker execution |
| app/memory/conversation_store.py | Memory | ConversationMemoryStore (SQLite) |
| app/observability/tracer.py | Tracing | RunTracer, node/run recording |
| mcp_server/server.py | Tool exposure | FastMCP with 7 tools |
| evals/runner.py | Eval | Test runner with metrics |
| pyproject.toml | Dependencies | LangGraph, Langfuse, Streamlit, etc. |

---

## 10. DEPLOYMENT TOPOLOGY

```
┌──────────────────────────────────────┐
│  Streamlit (Current)                 │
│  - Session state (thread_id)         │
│  - Chat history rendering            │
│  - File upload                       │
└────────┬─────────────────────────────┘
         │
         v
┌──────────────────────────────────────┐
│  app/main.py (run_query)             │
│  - Entry point (UI-agnostic)         │
│  - Graph selection (v1/v2)           │
│  - Tracer setup                      │
└────────┬─────────────────────────────┘
         │
         v
┌──────────────────────────────────────┐
│  LangGraph State Machine             │
│  - Explicit state transitions        │
│  - Conditional edges (routing)       │
│  - Send API (parallel workers)       │
└────────┬─────────────────────────────┘
         │
    ┌────┴─────┬──────────┬───────────┐
    │           │          │           │
    v           v          v           v
  Tools      Memory    Observability  E2B
  - SQL      - Conv    - RunTracer    - Viz
  - RAG      - Context - Langfuse
  - Files    - Qdrant  - JSONL
```

---

## 11. DEBUGGING & INSPECTION QUICK TIPS

### Trace your run
```bash
# Last trace entry (human-readable)
tail -1 evals/reports/traces.jsonl | python -m json.tool

# All traces for a run_id
grep '"run_id":"ABC123"' evals/reports/traces.jsonl | python -m json.tool
```

### View conversation history
```python
from app.memory import get_conversation_memory_store
store = get_conversation_memory_store()
turns = store.get_recent_turns("your-thread-id", limit=10)
for turn in turns:
    print(f"{turn.role}: {turn.content[:100]}")
```

### Understand graph execution order
```bash
# Export graph to image
uv run python export_graph.py
# Open docs/thangquang09/langgraph_graph.png
```

### Run tests
```bash
pytest tests/ -v
pytest tests/test_sql_tools.py -v
pytest -k "memory" --cov=app
```

---

**Generated**: 2026-04-02  
**Codebase Size**: ~15k SLOC (excluding tests, vendor, data)  
**Key Dependency**: LangGraph 1.1.3+ (Send API required for V2)  
**Default Graph**: V2 (Plan-and-Execute with parallelism)  
**Production Observability**: ✅ (Langfuse + JSONL traces)  
**Memory**: ✅ (Conversation-scoped via SQLite)  
**Safety**: ✅ (SQL validation, E2B sandboxing)
