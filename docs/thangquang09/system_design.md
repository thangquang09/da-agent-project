# System Design - DA Agent Lab

**Updated:** 2026-04-04

Mục tiêu của tài liệu này là mô tả chi tiết, kỹ thuật luồng end-to-end của DA Agent Lab — từ lúc user gửi query đến khi nhận được câu trả lời có truy vết.

---

## 1. Tổng quan kiến trúc

DA Agent Lab hiện là một **leader-first constrained agent** dùng LangGraph để điều phối, kết hợp:

- **Leader LLM** cho orchestration và high-level tool calling
- **Deterministic code + SQL worker subgraph** cho validation, execution, aggregation
- **SQLite** làm local data warehouse
- **Vector search đơn giản** (cosine similarity trên token counter) cho RAG docs
- **Session memory tối giản** với recent turns, summary, và `last_action`
- **Visualization infrastructure** với E2B sandbox cho data visualization
- **Observability** multi-layer: JSONL traces + Langfuse adapter
- **FastAPI backend** với streaming SSE cho real-time feedback

### High-level flow

```
User (CLI / Streamlit / HTTP API)
        |
        v
  FastAPI Backend (backend/main.py)
        |
        +-- /query endpoint handles requests
        +-- run_query_async (thread pool)  
        |
        v
  build_sql_v3_graph()   [LangGraph StateGraph - Leader Agent]
        |
        +-- process_uploaded_files
        |
        +-- inject_session_context
        |
        +-- leader_agent
        |         |
        |         +---> ask_sql_analyst
        |         +---> ask_sql_analyst_parallel
        |         +---> retrieve_rag_answer
        |         |
        |         +---> [parallel sql task fan-out / aggregate]
        |
        v
  final_payload
        |
        v
  capture_action_node   [save to conversation memory]
        |
        v
  compact_and_save_memory [compress and persist memory]
        |
        v
  Trace JSONL + Langfuse
```

> Ghi chú: các section sâu hơn của tài liệu này còn chứa mô tả lịch sử `V1/V2`. Source of truth runtime hiện tại là flow `V3` ở phần trên.

---

## 2. State Model

### 2.1 AgentState (TypedDict, total=False)

Trạng thái chính được chia sẻ giữa tất cả các node qua LangGraph state:

```python
class AgentState(TypedDict, total=False):
    # --- Input ---
    user_query: str                      # Câu hỏi của user
    target_db_path: str                  # đường dẫn SQLite DB (optional)
    user_semantic_context: str           # Context được user cung cap trực tiếp
    uploaded_files: list[str]           # Files upload (CSV, etc.)
    uploaded_file_data: list[dict]      # File data (name, base64 encoded bytes)
    thread_id: str                       # Session/thread identifier for memory continuity
    
    # --- Routing ---
    intent: Intent                        # sql | rag | mixed | unknown
    intent_reason: str                    # Lý do LLM để cấp intent
    
    # --- Messages (accumulate) ---
    messages: Annotated[list[dict], operator.add]
    
    # --- Schema & Context ---
    schema_context: str                   # JSON mô tả tables/columns (tu get_schema)
    dataset_context: str                  # JSON stats: row counts, min/max dates, samples
    user_semantic_context: str
    retrieved_dataset_context: list[dict] # RAG chunks tim được cho context_type
    session_context: str                  # Context from conversation memory (continuity detection)
    
    # --- Memory ---
    conversation_memory: list[dict]       # Previous conversation turns
    memory_compacted: bool               # Whether memory has been compacted
    continuity_detected: bool            # Whether this is an implicit follow-up
    continuity_context: str              # Context from previous turns for continuity
    
    # --- Planning (v2 Graph) ---
    planned_tasks: list[dict]             # Subtasks from task_planner
    task_results: Annotated[list[dict], operator.add]  # Results from parallel workers
    current_task_index: int               # Index of current task being processed
    
    # --- SQL Path ---
    generated_sql: str                    # SQL thuần LLM generate
    validated_sql: str                    # SQL da được validate (sanitized, limit applied)
    sql_result: dict                     # {rows, row_count, columns, latency_ms}
    
    # --- Analysis ---
    analysis_result: dict                 # {summary, trend, insights} - LLM phan tích
    
    # --- RAG Path ---
    retrieved_context: list[dict]         # RAG chunks tu business docs
    
    # --- Visualization ---
    visualization_request: dict           # Request for chart/table visualization
    visualization_result: dict            # Result from E2B sandbox visualization
    
    # --- Synthesis ---
    final_answer: str
    final_payload: AnswerPayload          # Cau truc tra loi cuoi cung
    
    # --- Observability (accumulate) ---
    tool_history: Annotated[list[dict], operator.add]  # Moi node them 1 entry
    errors: Annotated[list[dict], operator.add]        # Loi neu co
    
    # --- Metadata ---
    step_count: int
    confidence: Confidence                # high | medium | low
    run_id: str
    expected_keywords: list[str]          # Tu eval case (chi dung trong eval)
    context_type: ContextType             # user_provided | csv_auto | mixed | default
```

### 2.2 GraphInputState / GraphOutputState

```python
class GraphInputState(TypedDict, total=False):
    user_query: str
    target_db_path: str
    user_semantic_context: str
    uploaded_files: list[str]

class GraphOutputState(TypedDict, total=False):
    final_answer: str
    final_payload: AnswerPayload
    intent: Intent
    intent_reason: str
    errors: list[dict]
    step_count: int
    run_id: str
    context_type: ContextType
```

---

## 3. Graph Construction

### 3.1 Nodes

| Node | Type | Responsibility |
|------|------|----------------|
| `detect_context_type` | classifier | phân loại input: `user_provided`, `csv_auto`, `mixed`, `default` |
| `process_uploaded_files` | tool | Validate, profile, and auto-register uploaded CSV files |
| `detect_continuity_node` | memory | Detect implicit follow-ups in conversation memory |
| `inject_session_context` | memory | Inject context from conversation memory |
| `route_intent` | agent (LLM) | LLM classify query thanh `sql`, `rag`, `mixed`, `unknown` |
| `get_schema` | retriever | Lay schema + dataset stats tu SQLite |
| `generate_sql` | generation (LLM) | LLM generate SQL tu query + schema |
| `validate_sql_node` | guardrail | Validate SQL: read-only, known tables, limit clause |
| `execute_sql_node` | tool | Execute validated SQL, return rows |
| `analyze_result` | chain (LLM) | LLM phan tích ket qua, tao summary/trend/insights |
| `retrieve_context_node` | retriever | RAG retrieval: metric_definition hoac business_context |
| `task_planner` | planner (LLM) | Decompose query into parallelizable subtasks |
| `sql_worker` | subgraph | Execute individual SQL tasks in parallel |
| `standalone_visualization` | visualization | Generate charts/visualizations via E2B sandbox |
| `aggregate_results` | aggregator | Combine results from parallel workers |
| `synthesize_answer` | generation | Tong hop tra loi cuoi cung tu tat ca signal |
| `capture_action_node` | memory | Capture actions and save to conversation memory |
| `compact_and_save_memory` | memory | Compact and persist conversation memory |

### 3.2 Edges

```python
# edges.py

# V1 routing
route_after_context_detection  --> process_uploaded_files OR inject_session_context
route_after_intent             --> sql/mixed -> get_schema
                                --> rag       -> retrieve_context_node  
                                --> unknown   -> synthesize_answer

route_after_sql_validation     --> no errors -> execute_sql_node
                                --> has errors && mixed -> retrieve_context_node
                                --> has errors && !mixed -> synthesize_answer

route_after_analysis           --> mixed -> retrieve_context_node
                                --> !mixed -> synthesize_answer

# V2 routing (Plan-and-Execute)
route_to_execution_mode        --> sql/mixed -> task_planner
                                --> rag       -> retrieve_context_node
                                --> unknown   -> synthesize_answer

route_after_planning           --> Send API fan-out to sql_worker(s) and/or standalone_visualization
route_after_worker_execution   --> aggregate_results OR synthesize_answer
```

### 3.3 Node Instrumentation

Moi node được bao boi `_instrument_node()` de tu dong goi tracer:

```python
def _instrument_node(node_name, fn, observation_type):
    def _wrapped(state):
        tracer = get_current_tracer()
        scope = tracer.start_node(node_name, state, observation_type)
        try:
            update = fn(state)
        except Exception:
            tracer.end_node(scope, error=exc)
            raise
        tracer.end_node(scope, update=update)
        return update
    return _wrapped
```

Observation types: `span`, `agent`, `classifier`, `retriever`, `tool`, `generation`, `chain`, `guardrail`

---

## 4. Detailed Node Breakdown

### 4.1 detect_context_type

**Input:** `user_semantic_context`, `uploaded_files` (tu state)

**Logic:**
```python
def _detect_context_type(user_context, uploaded_files):
    if user_context and uploaded_files:  return ("mixed", user_context)
    if user_context:                     return ("user_provided", user_context)
    if uploaded_files:                   return ("csv_auto", None)
    return ("default", None)
```

**Output:** `context_type`, cap nhat `tool_history`, `step_count`

**Routing:** Luon di tiep đến `process_uploaded_files` hoac `inject_session_context`

### 4.2 process_uploaded_files

**Input:** `uploaded_files`, `uploaded_file_data`, `target_db_path` (tu state)

**Logic:**
1. Neu `uploaded_file_data` co san: validate va auto-register CSV qua `auto_register_csv()` tool
2. Neu chi co `uploaded_files`: doc file va validate qua `validate_csv()` tool
3. Profile data qua `profile_csv()` tool de xac dinh schema va data types
4. Tao bang SQLite moi với ten duy nhat va insert du lieu

**CSV Tools:**
- `validate_csv()`: Kiem tra file size, encoding, delimiter, column sanitization
- `profile_csv()`: Pandas-based profiling với type inference
- `auto_register_csv()`: Full pipeline (validate → profile → CREATE TABLE → INSERT)

**Output:** Cap nhat `target_db_path` neu co CSV moi, `tool_history`, `step_count`

**Routing:** Luon di tiep đến `inject_session_context`

### 4.3 detect_continuity_node

**Input:** `user_query`, `thread_id`, `conversation_memory` (tu state)

**Logic:**
1. Truy van Qdrant vector store de tim cac tin nhan lien quan trong conversation memory
2. Dung embedding similarity de phat hien implicit follow-up queries
3. So sanh với cac tin nhan truoc do trong cung thread

**Memory Integration:**
- sử dụng `ConversationMemoryStore` singleton với SQLite backend
- Co check_same_thread=False de đảm bảo thread safety trong async environment
- Tach rieng conversation context de inject vao subsequent queries

**Output:** `continuity_detected`, `continuity_context`, `tool_history`, `step_count`

**Routing:** Luon di tiep đến `route_intent`

### 4.4 inject_session_context

**Input:** `thread_id`, `conversation_memory` (tu state)

**Logic:**
1. Lay conversation history tu Qdrant vector store
2. Trich xuat semantic context tu cac tin nhan truoc do
3. Gop với `user_semantic_context` neu co

**Output:** `session_context`, `tool_history`, `step_count`

**Routing:** Luon di tiep đến `detect_continuity_node`

### 4.5 route_intent (LLM-driven)

**Input:** `user_query`

**LLM Call:**
- Model: `gh/gpt-4o-mini` (configurable)
- Temperature: 0.0
- Prompt: `ROUTER_PROMPT_DEFINITION` ( qua `PromptManager`)

**Prompt (`router.py`):**
```
You are an intent router for a Data Analyst Agent.
Classify the query into exactly one intent:
- sql: needs numeric values, trends, rankings, comparisons from structured data.
- rag: needs definitions, caveats, business rules, or qualitative context.
- mixed: needs both data and business context.
- unknown: capability, help, or casual questions that don't require SQL/RAG.

Return JSON only with shape:
{"intent":"sql|rag|mixed|unknown","reason":"short reason"}
No markdown. No extra keys.
```

**Output parsing:** Extract JSON tu LLM response, validate intent la 1 trong 4 gia tri hop le. Neu invalid thi `intent="unknown"`, `intent_reason="llm_invalid_output"`.

**Output:** `intent`, `intent_reason`, `tool_history` ( với `token_usage`, `cost_usd`), `step_count`

### 4.6 task_planner (LLM-driven, V2 only)

**Input:** `user_query`, `schema_context`, `dataset_context`, `intent` (tu state)

**Logic:**
1. Phan tích query de xac dinh cac subtasks co the thuc hien song song
2. Tao danh sach `TaskState` objects với `execution_mode` (single/parallel/linear)
3. Xac dinh xem co can visualization hay khong

**LLM Call:**
- Model: `gh/gpt-4o` (configurable cho planning)
- Temperature: 0.0
- Prompt: Co few-shot examples de đảm bảo JSON output structure

**Output:** `task_plan` (list of `TaskState`), `execution_mode`, `tool_history`, `step_count`

**Routing:** sử dụng Send API de fan-out đến cac `sql_worker` va `standalone_visualization_worker`

### 4.7 sql_worker (subgraph, V2 only)

**Input:** `TaskState` (tu task_planner qua Send API)

**Subgraph architecture:**
- `get_schema` → `generate_sql` → `validate_sql_node` → `execute_sql_node` → `analyze_result`
- Neu `requires_visualization` = True: `visualization_node` (cuoi cung)

**Nested sequential trong parallel fan-out:**
- SQL execution va visualization cho cung mot task luon la sequential (dung dependency order)
- Cac tasks khác van chay song song qua Send API fan-out

**Output:** Hoan thanh task va return result ve cho `task_results` accumulation

**Routing:** Ket qua được accumulate qua `operator.add` va gui ve `aggregate_results`

### 4.8 standalone_visualization (V2 only)

**Input:** `user_query`, raw data neu co

**Logic:**
1. Nhan dien yeu cau visualization tu query
2. Sinh ma Python (matplotlib/seaborn) de tao chart
3. Thuc thi ma trong E2B sandbox với data an toan
4. Tra ve image data (PNG/JPEG) ve cho Streamlit

**E2B Integration:**
- Conditional import pattern (optional dependency)
- Graceful degradation neu E2B_API_KEY khong co
- Upload data toi sandbox va nhan ket qua image ve

**Output:** `visualization_result`, `tool_history`, `step_count`

**Routing:** Gui ket qua ve `aggregate_results`

### 4.9 aggregate_results (V2 only)

**Input:** `task_results` (accumulated tu cac sql_worker)

**Logic:**
1. Gom nhom ket qua tu cac tasks song song
2. Noi cac ket qua thanh mot response duy nhat
3. Trich xuat visualization neu co

**Accumulation pattern:**
- sử dụng `Annotated[list[TaskState], operator.add]` de fan-in ket qua
- Deterministic accumulation qua Python operators

**Output:** `aggregated_results`, `tool_history`, `step_count`

**Routing:** Gui ket qua ve `synthesize_answer`

### 4.10 capture_action_node (Memory)

**Input:** `final_payload`, `thread_id`, `user_query`

**Logic:**
1. Ghi lai hanh dong nguoi dung va ket qua tra ve vao conversation memory
2. Luu tru trong Qdrant vector store với thread context
3. Danh dau cho cac lan truy van tiep theo

**Output:** Cap nhat `conversation_memory`, `tool_history`, `step_count`

**Routing:** Gui tiep đến `compact_and_save_memory`

### 4.11 compact_and_save_memory (Memory)

**Input:** `conversation_memory`, `thread_id`

**Logic:**
1. Nen conversation memory de giam dung luong
2. Luu tru vao Qdrant vector store
3. đảm bảo performance cho cac lan truy van tiep theo

**Memory management:**
- cơ chế compaction de giu dung luong o muc hop ly
- Thread-isolated de tranh conflict giữa cac session

**Output:** `memory_compacted`, `tool_history`, `step_count`

**Routing:** Ket thuc graph flow

---

### 4.2 route_intent (LLM-driven)

**Input:** `user_query`

**LLM Call:**
- Model: `gh/gpt-4o-mini` (configurable)
- Temperature: 0.0
- Prompt: `ROUTER_PROMPT_DEFINITION` ( qua `PromptManager`)

**Prompt (`router.py`):**
```
You are an intent router for a Data Analyst Agent.
Classify the query into exactly one intent:
- sql: needs numeric values, trends, rankings, comparisons from structured data.
- rag: needs definitions, caveats, business rules, or qualitative context.
- mixed: needs both data and business context.
- unknown: capability, help, or casual questions that don't require SQL/RAG.

Return JSON only with shape:
{{"intent":"sql|rag|mixed|unknown","reason":"short reason"}}
No markdown. No extra keys.
```

**Output parsing:** Extract JSON tu LLM response, validate intent la 1 trong 4 gia tri hop le. Neu invalid thi `intent="unknown"`, `intent_reason="llm_invalid_output"`.

**Output:** `intent`, `intent_reason`, `tool_history` ( với `token_usage`, `cost_usd`), `step_count`

---

### 4.3 get_schema

**Input:** `target_db_path`, `context_type` (tu state)

**Logic:**
1. Neu `enable_mcp_tool_client=True`: goi MCP tools `get_schema` va `dataset_context`
2. Neu khong: goi trực tiếp `get_schema_overview()` va `dataset_context()` (local)

**`get_schema_overview()`** (tools/get_schema.py):
```python
def get_schema_overview(db_path):
    tables = list_tables(db_path)  # SELECT name FROM sqlite_master WHERE type='table'
    return {
        "tables": [
            {
                "table_name": table,
                "columns": describe_table(table)  # PRAGMA table_info
            }
            for table in tables
        ]
    }
```

**`dataset_context()`** (tools/dataset_context.py):
```python
# Tra ve JSON với:
# - row_counts: {table_name: count}
# - date_ranges: {table: {"min": date, "max": date}}
# - samples: {table_name: [row1, row2]}
```

**Dataset Context Retrieval** (chi khi `context_type in user_provided, csv_auto, mixed`):
- Query RAG index với `top_k=3` de lay `retrieved_dataset_context`
- Giup LLM hieu ve data khi user cung cap them context

**Output:** `schema_context` (JSON string), `dataset_context` (JSON string), `retrieved_dataset_context`, `tool_history`, `step_count`

---

### 4.4 generate_sql (LLM-driven)

**Input:** `user_query`, `schema_context`, `dataset_context`, `semantic_context` (tu state)

**Semantic Context Building:**
```python
def _build_semantic_context(state):
    parts = []
    if user_context := state.get("user_semantic_context"):
        parts.append(f"[User provided]: {user_context}")
    if retrieved := state.get("retrieved_dataset_context"):
        chunks = [f"- [{item.source}] {item.text[:200]}" for item in retrieved[:3]]
        parts.append("[Relevant context]:\n" + "\n".join(chunks))
    return "\n\n".join(parts)
```

**LLM Call:**
- Model: `gh/gpt-4o-mini`, temperature 0.0
- Prompt: `SQL_PROMPT_DEFINITION` ( qua `PromptManager`)

**Prompt (`sql.py`):**
```
You are a SQLite SQL generator for analytics.
Rules:
- Read-only queries only (SELECT or WITH ... SELECT).
- Only use tables/columns from the provided schema context.
- Prefer LIMIT clauses to keep results small (<=200 rows).
- Always keep language neutral and precise; return SQL text only.
```

**SQL Extraction:** Parse markdown-fenced code blocks, hoac tim first `SELECT/WITH` statement.

**Output:** `generated_sql`, `tool_history` (với `generation_status`: `llm_generated` | `llm_empty_output` | `llm_error:*`), `step_count`

---

### 4.5 validate_sql_node (Deterministic)

**Input:** `generated_sql`, `target_db_path`

**Validation (`tools/validate_sql.py`):**

1. **Empty check:** SQL must not be empty
2. **Multiple statements:** No `;` allowed
3. **Read-only check:** Must match `^\s*(SELECT|WITH)\b`
4. **Forbidden keywords:** INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, REPLACE, ATTACH, DETACH, PRAGMA
5. **Table existence:** All tables must exist in `sqlite_master` (hoac la CTE names)
6. **Auto-limit:** Neu chua co `LIMIT`, them `LIMIT {max_limit}` (default 200)

```python
@dataclass(frozen=True)
class SQLValidationResult:
    is_valid: bool
    sanitized_sql: str
    reasons: list[str]       # Cac loi neu invalid
    detected_tables: list[str]
```

**Output:** `validated_sql` (sanitized), `tool_history`, `step_count`. Neu invalid, them error vao `errors`:
```python
{"category": "SQL_VALIDATION_ERROR", "message": "; ".join(reasons)}
```

---

### 4.6 execute_sql_node

**Input:** `validated_sql`, `target_db_path`

**Execution:**
```python
def query_sql(sql, db_path):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql)
        rows = [dict(row) for row in cur.fetchall()]
    return {
        "rows": rows,
        "row_count": len(rows),
        "columns": [desc[0] for desc in cur.description],
        "latency_ms": round((time.perf_counter() - start) * 1000, 2)
    }
```

**MCP mode:** Neu `enable_mcp_tool_client=True`, goi `query_sql` qua MCP server

**Output:** `sql_result`, `tool_history`, `step_count`. Neu rejected by validator, add error:
```python
{"category": "SQL_VALIDATION_ERROR", "message": "; ".join(validation_reasons)}
```

---

### 4.7 analyze_result (LLM-driven)

**Input:** `sql_result.rows`, `user_query`, `validated_sql`, `expected_keywords`

**LLM Call:** Model `gh/gpt-4o-mini`, temperature 0.0

**Prompt:** `ANALYSIS_PROMPT_DEFINITION` ( qua `PromptManager`)

**Prompt (`analysis.py`):**
```
You are a data analyst assistant. Analyze SQL query results...
{{#if expected_keywords}}
- Expected keywords to naturally incorporate: {{expected_keywords}}
{{/if}}
...
Provide your analysis in this JSON format:
{{{"summary": "...", "insights": ["...", "..."]}}}}
```

**Output:** `analysis_result` = `{summary, trend, insights}`, `tool_history`, `step_count`

---

### 4.8 retrieve_context_node (LLM-driven retrieval type selection)

**Input:** `user_query`, `intent`

**Retrieval Type Decision (LLM):**
```python
def _llm_decide_retrieval_type(query):
    # LLM quyết định: metric_definition hay business_context
    system = "You are a query classifier... 1='metric_definition', 2='business_context'"
    response = client.chat_completion(messages=[{"role":"system",...}, {"role":"user",...}])
    # Parse JSON response
    return retrieval_type  # 'metric_definition' | 'business_context'
```

**Retrieval:**
- `metric_definition`: query RAG index với `source_filter=METRIC_DOCS` (metric_definitions.md, retention_rules.md)
- `business_context`: query RAG index với `source_filter=None` (tat ca docs)

**RAG Index (`app/rag/index_docs.py`):**
```python
def query_index(query, top_k, source_filter):
    # 1. Tokenize query thanh Counter (bag-of-words)
    # 2. Compute cosine similarity với moi chunk trong index
    # 3. Sort by score descending, tra ve top_k
    return [{"source", "chunk_id", "score", "text"}, ...]
```

**Output:** `retrieved_context` (list of chunks), `tool_history`, `step_count`

---

### 4.9 synthesize_answer

**Input:** `intent`, `errors`, `sql_result`, `analysis_result`, `retrieved_context`, `tool_history`

**Synthesis by intent:**

**sql:**
- Co loi: `answer = "Cannot answer safely because SQL validation failed: {error_msg}"`
- Khong loi: `answer = analysis.summary`, confidence `high` neu co rows, `medium` neu empty

**rag:**
- Co context: `answer = "From business docs: " + context_evidence`
- Khong context: `answer = "I could not retrieve relevant business documentation..."`

**mixed:**
- Ca hai: `answer = "Data signal: {analysis.summary}\nBusiness context:\n{context_evidence}"`
- Chi SQL: `answer = "Partial answer (SQL branch succeeded, retrieval branch missing): {analysis.summary}"`
- Chi context: `answer = "Partial answer (retrieval branch succeeded, SQL branch failed): {context_evidence}"`
- Khong gì: `answer = "I could not complete either SQL or retrieval branch..."`

**unknown:** (fully LLM-driven fallback)
```python
def _llm_synthesize_fallback(query, intent, errors):
    system = "You are a helpful data analyst assistant..."
    response = client.chat_completion(messages=[...])
    return content
```

**Groundedness check:**
```python
def _unsupported_numeric_claims(answer, evidence):
    answer_numbers = re.findall(r"\b\d+(?:[.,]\d+)?%?\b", answer)
    evidence_numbers = re.findall(...) in evidence
    return [f"numeric_claim:{n}" for n in answer_numbers if n not in evidence_numbers]
```

**Output:** `final_answer`, `final_payload` (AnswerPayload), `confidence`, `step_count`

```python
class AnswerPayload(TypedDict, total=False):
    answer: str
    evidence: list[str]
    confidence: Confidence
    used_tools: list[str]
    generated_sql: str
    error_categories: list[str]
    step_count: int
    total_token_usage: int
    total_cost_usd: float
    unsupported_claims: list[str]
    context_type: ContextType
```

---

## 5. RAG Layer

### 5.1 Document Indexing

**Source docs:** `docs/research/rag/`
- `metric_definitions.md` - dinh nghia DAU, revenue, retention, etc.
- `retention_rules.md` - cac quy tac tinh retention
- `revenue_caveats.md` - caveats cho revenue
- `data_quality_notes.md` - data quality notes

**Indexing process:**
```python
def build_local_index(docs_dir):
    records = []
    for path in docs_dir.glob("*.md"):
        content = path.read_text()
        chunks = _chunk_text(content, chunk_size=140, overlap=30)
        for chunk_id, chunk in enumerate(chunks, 1):
            records.append(ChunkRecord(
                source=path.name,
                chunk_id=chunk_id,
                text=chunk,
                vector=_embed_text(chunk)  # Counter of lowercase tokens
            ))
    return tuple(records)
```

**Embedding:** Bag-of-words token counter (khong dung external embedding model)

**Similarity:** Cosine similarity tren token vectors:
```python
def cosine_similarity(left, right):
    common = set(left.keys()) & set(right.keys())
    dot = sum(left[t] * right[t] for t in common)
    norm = sqrt(sum(v*v for v in left.values())) * sqrt(sum(v*v for v in right.values()))
    return dot / norm if norm else 0.0
```

### 5.2 Retrieval Types

| Type | Filter | Use case |
|------|--------|----------|
| `metric_definition` | `METRIC_DOCS = {"metric_definitions.md", "retention_rules.md"}` | Hoi ve dinh nghia, formula |
| `business_context` | `None` (all docs) | Hoi ve caveats, business rules, quality notes |

---

## 6. LLM Integration

### 6.1 LLMClient (`app/llm/client.py`)

Wrapper cho OpenAI-compatible API:

```python
class LLMClient:
    @classmethod
    def from_env(cls) -> "LLMClient":
        return cls(settings=load_settings())
    
    def chat_completion(self, messages, model, temperature, stream=False):
        # POST to self.settings.llm_api_url
        # Headers: Authorization: Bearer {llm_api_key}
        # Body: {model, messages, temperature, stream: False}
        # Returns parsed JSON response
```

**Token tracking:** Normalize usage tu response, estimate cost USD dua tren model pricing table.

**Cost estimation:**
```python
DEFAULT_MODEL_PRICING_USD_PER_1M = {
    "gh/gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gh/gpt-4o": {"input": 2.50, "output": 10.00},
}
```

### 6.2 Prompt Management (`app/prompts/manager.py`)

**PromptManager** ho tro:
- **Langfuse integration:** Fetch prompts tu Langfuse neu co, fallback sang local definitions
- **Template variable substitution:** `{{variable}}` → value
- **Conditional blocks:** `{{#if var}}...{{/if}}`
- **Cache:** Langfuse prompts được cache 300s (configurable)

```python
prompt_manager = PromptManager()

prompt_manager.router_messages(query)         # → list[dict]
prompt_manager.sql_messages(query, schema, dataset, semantic)  # → list[dict]
prompt_manager.analysis_messages(query, sql, results, keywords)  # → list[dict]
```

### 6.3 Prompt Definitions

| Prompt | File | Used by |
|--------|------|---------|
| `da-agent-router` | `router.py` | `route_intent` |
| `da-agent-sql-generation` | `sql.py` | `generate_sql` |
| `da-agent-analysis` | `analysis.py` | `analyze_result` |

---

## 7. Observability

### 7.1 Tracer Architecture

**Three-layer tracing:**

1. **RunTracer** (`app/observability/tracer.py`): Manages entire run lifecycle
2. **LangfuseAdapter**: Syncs traces to Langfuse cloud (if enabled)
3. **JSONL persistence**: Appends records to `evals/reports/traces.jsonl`

### 7.2 Record Types

**NodeTraceRecord:**
```python
{
    "record_type": "node",
    "run_id", "node_name", "attempt",
    "status": "ok" | "error",
    "started_at", "ended_at",
    "latency_ms",
    "input_summary": {intent, step_count, has_schema_context, ...},
    "output_summary": {keys, intent, step_count, ...},
    "error_category", "error_message",
    "observation_type"
}
```

**RunTraceRecord:**
```python
{
    "record_type": "run",
    "run_id", "thread_id",
    "started_at", "ended_at", "latency_ms",
    "query", "routed_intent", "status",
    "total_steps", "used_tools",
    "generated_sql", "retry_count", "fallback_used",
    "error_categories", "total_token_usage", "total_cost_usd",
    "final_confidence"
}
```

### 7.3 Failure Taxonomy

| Category | Trigger |
|----------|---------|
| `ROUTING_ERROR` | `route_intent` fails |
| `SQL_GENERATION_ERROR` | `generate_sql` fails |
| `SQL_VALIDATION_ERROR` | `validate_sql_node` rejects SQL |
| `SQL_EXECUTION_ERROR` | `execute_sql_node` fails |
| `RAG_RETRIEVAL_ERROR` | `retrieve_context_node` fails |
| `RAG_IRRELEVANT_CONTEXT` | intent rag/mixed but 0 chunks retrieved |
| `EMPTY_RESULT` | intent sql/mixed but row_count == 0 |
| `SYNTHESIS_ERROR` | `synthesize_answer` or graph fails |
| `STEP_LIMIT_REACHED` | Recursion limit exceeded |

### 7.4 Langfuse Integration

- Conditional: chỉ active nếu `enable_langfuse=True` và có đủ `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`
- Records được flush sau mỗi run
- Metadata chứa project/org info để phân biệt environments

---

## 8. Evaluation System

### 8.1 Eval Cases (`evals/case_contracts.py`)

```python
@dataclass(frozen=True)
class EvalCase:
    id: str
    suite: SuiteName           # domain | spider | movielens
    language: Language         # vi | en
    query: str
    expected_intent: IntentName
    expected_tools: list[str]
    should_have_sql: bool
    expected_keywords: list[str]  # for groundedness check
    target_db_path: str | None
    gold_sql: str | None
    metadata: dict
```

### 8.2 Eval Suites

| Suite | Source | Description |
|-------|--------|-------------|
| `domain` | `domain_cases.jsonl` | 36 bilingual cases: SQL/RAG/Mixed, business metrics |
| `spider` | Spider benchmark | Text-to-SQL benchmark, EN only |
| `movielens` | MovieLens dataset | Auto-generated cases |

### 8.3 Eval Metrics

| Metric | Description |
|--------|-------------|
| `routing_accuracy` | predicted_intent == expected_intent |
| `tool_path_accuracy` | all expected_tools in used_tools |
| `sql_validity_rate` | generated_sql passes validate_sql |
| `answer_format_validity` | payload has required keys |
| `groundedness_pass_rate` | score >= 0.70 (keyword + LLM fallback) |
| `spider_exact_match_rate` | SQL component comparison |
| `spider_exact_match_avg_f1` | F1 score for SQL components |
| `avg_answer_quality_score` | LLM-as-judge answer quality |

### 8.4 Gate Thresholds

```python
GATE_THRESHOLDS = {
    "routing_accuracy": 0.90,
    "sql_validity_rate": 0.90,
    "tool_path_accuracy": 0.95,
    "answer_format_validity": 1.00,
    "groundedness_pass_rate": 0.70,
}
```

### 8.5 Groundedness Evaluation (`evals/groundedness.py`)

**Hybrid approach:**
1. **Keyword matching:** Check if `expected_keywords` appear in answer
2. **LLM fallback:** If keyword score < 0.5, use LLM to evaluate semantic groundedness

```python
def evaluate_groundedness(answer, evidence, expected_keywords, use_llm_fallback=True):
    keyword_result = _keyword_groundedness(answer, evidence, expected_keywords)
    if use_llm_fallback and keyword_result.score < 0.5 and expected_keywords:
        llm_result = _llm_evaluate_groundedness(answer, evidence, expected_keywords)
        if llm_result.score > keyword_result.score:
            return llm_result
    return keyword_result
```

**Scoring:**
- Keyword score = `len(supported_keywords) / len(expected_keywords)`
- Claim penalty = `min(0.5, 0.1 * len(unsupported_claims))`
- Final score = `max(0.0, keyword_score - claim_penalty)`
- Pass = `score >= 0.7 and not unsupported_claims`

### 8.6 Eval Runner (`evals/runner.py`)

**Execution flow:**
```python
def run_case(case, recursion_limit):
    # 1. Invoke graph via run_query()
    payload = run_query(case.query, db_path=case.target_db_path, 
                        expected_keywords=case.expected_keywords)
    # 2. Extract metrics
    # 3. Run evaluators (spider_exact_match, execution_accuracy, answer_judge)
    # 4. Evaluate groundedness
    # 5. Determine failure_bucket
    return CaseResult(...)
```

**Parallel execution:** `ThreadPoolExecutor` with configurable workers (default 4)

**Output:**
- `evals/reports/summary_{suite}_{split}_{timestamp}.json`
- `evals/reports/summary_{suite}_{split}_{timestamp}.md`
- `evals/reports/per_case_{suite}_{split}_{timestamp}.jsonl`
- `evals/reports/latest_summary.{json,md}` (symlink-like latest)

---

## 9. Data Layer

### 9.1 SQLite Databases

| Database | Path | Tables |
|----------|------|--------|
| `analytics.db` | `data/warehouse/analytics.db` | `daily_metrics`, `videos` |
| `domain_eval.db` | `data/warehouse/domain_eval.db` | Same as above |
| `movielens.db` | `data/warehouse/movielens.db` | `movies`, `ratings`, `tags`, `genome_scores` |
| `movielens_sample.db` | `data/warehouse/movielens_sample.db` | Sampled version |

### 9.2 Schema: analytics.db / domain_eval.db

**daily_metrics:**
```sql
CREATE TABLE daily_metrics (
    date TEXT PRIMARY KEY,
    dau INTEGER,
    revenue REAL,
    retention_d1 REAL,
    avg_session_time REAL
);
```

**videos:**
```sql
CREATE TABLE videos (
    video_id TEXT PRIMARY KEY,
    title TEXT,
    publish_date TEXT,
    views INTEGER,
    watch_time REAL,
    retention_rate REAL,
    ctr REAL
);
```

### 9.3 Dataset Context Stats

`dataset_context` query cung cap:
- Row counts cho moi table
- Min/max dates (neu co date column)
- Sample rows (2-3 rows moi table)

---

## 10. Entry Points

### 10.1 CLI (`app/main.py`)

```bash
python -m app.main "DAU 7 ngày gần đây như thế nào?" --db-path data/warehouse/domain_eval.db
```

### 10.2 FastAPI Backend (`backend/main.py`)

```bash
# Start FastAPI server
uv run python -m backend.main

# Or with uvicorn
uvicorn backend.main:app --host 0.0.0.0 --port 8001
```

**Backend Features:**
- Async endpoints với thread pool cho LangGraph execution
- Streaming SSE cho real-time progress feedback
- CORS middleware cho Streamlit integration
- Pre-warming cho embedding model va conversation store
- Auto-seeding cho analytics.db neu chua ton tai

**Endpoints:**
- `POST /query` - Non-streaming query processing
- `POST /query/upload` - File upload endpoint
- `GET /query/stream` - Streaming SSE endpoint
- `GET /health` - Health check
- `GET /threads` - Thread/conversation management
- `POST /evals/run` - Eval execution endpoint

### 10.3 Streamlit Thin Client (`streamlit_app.py`)

```
streamlit run streamlit_app.py
```

Features:
- SSE streaming integration với backend
- Real-time progress feedback trong khi agent lam viec
- Chat interface với queue
- Sample query buttons (SQL/RAG/Mixed examples)
- Debug tabs: SQL, Trace, Errors, Raw JSON
- Metrics: Confidence, Intent, Tools Used, Tokens, Cost
- File upload với multipart form data

### 10.4 Eval Runner

```bash
# Full eval
uv run python -m evals.runner --suite all

# Domain only (fast, 12 cases)
uv run python -m evals.runner --suite domain --limit 12

# Spider dev with gates
uv run python -m evals.runner --suite spider --split dev --enforce-gates
```

### 10.5 MCP Server (`mcp_server/server.py`)

```bash
python -m mcp_server.server
```

Exposes tools qua FastMCP với 2 transport modes:
- `stdio` - Per-call spawn (legacy, latency cao)
- `streamable-http` - Persistent connection (moi, latency thap)

---

## 11. Flow Walkthroughs

### 11.1 SQL Intent Path

**Query:** "DAU 7 ngày gần đây có xu hướng tăng hay giảm?"

```
START
  |
  v
detect_context_type
  | context_type="default"
  v
route_intent
  | LLM returns {"intent": "sql"}
  v
get_schema
  | schema_context + dataset_context
  v
generate_sql
  | LLM generates: "SELECT date, dau FROM daily_metrics ORDER BY date DESC LIMIT 7"
  v
validate_sql_node
  | is_valid=True, sanitized_sql=original + " LIMIT 200"
  v
execute_sql_node
  | sql_result = {rows: [...], row_count: 7}
  v
analyze_result
  | LLM analyzes: {"summary": "DAU có xu hướng giảm nhẹ...", "trend": "giảm"}
  v
route_after_analysis
  | intent=mixed? No -> synthesize_answer
  v
synthesize_answer
  | answer = analysis.summary, confidence=high
  v
END
```

### 11.2 RAG Intent Path

**Query:** "Retention D1 là gì?"

```
START
  |
  v
detect_context_type
  v
route_intent
  | LLM returns {"intent": "rag"}
  v
route_after_intent
  | -> retrieve_context_node
  v
retrieve_context_node
  | _llm_decide_retrieval_type -> "metric_definition"
  | RAG query with source_filter=METRIC_DOCS
  | retrieved_context = [{"source": "metric_definitions.md", "text": "..."}]
  v
route_after_analysis (skip - directly to synthesize)
  v
synthesize_answer
  | answer = "From business docs: - metric_definitions.md (score=0.85): Retention D1 là..."
  | confidence=medium
  v
END
```

### 11.3 Mixed Intent Path

**Query:** "DAU 7 ngày gần đây thay đổi ra sao và metric này định nghĩa thế nào?"

```
START
  |
  v
detect_context_type
  v
route_intent
  | LLM returns {"intent": "mixed"}
  v
get_schema -> generate_sql -> validate_sql_node -> execute_sql_node -> analyze_result
  |                                                                  |
  v                                                          route_after_analysis
route_after_analysis                                                  |
  | intent=mixed                                                        v
  v                                                              retrieve_context_node
route_after_context_detection (trong synthesize)                       |
  v                                                                    v
synthesize_answer                                                      |
  | answer = "Data signal: {analysis.summary}\nBusiness context:\n{context_evidence}"
  | confidence=high
  v
END
```

---

## 12. MCP Integration

### 12.1 MCP Server (`mcp_server/server.py`)

Exposes tools via FastMCP:
- `get_schema`: Tra ve schema overview
- `query_sql`: Execute read-only SQL
- `retrieve_metric_definition`: RAG metric definition
- `dataset_context`: Lay stats cua database

### 12.2 MCP Client (`app/tools/mcp_client.py`)

```python
def call_mcp_tool(tool_name, args):
    # Persistent HTTP connection (streamable-http)
    # Auto-starts server if not running
    # Returns parsed tool response
```

**Transport modes:**
- `streamable-http`: Persistent connection, low latency
- `stdio`: Spawn per call (legacy, high latency)

---

## 13. Key Design Decisions

### 13.1 Constrained Agent vs Unconstrained

System được thiet ke la **constrained agent**:
- LLM chi được phep goi cac tools dã định nghĩa
- SQL phải pass validation trước khi execute
- Không có "tool injection" hay "prompt injection" protection trong V1 này

### 13.2 Deterministic vs LLM Decisions

| Component | Approach | Reason |
|-----------|----------|--------|
| SQL validation | Deterministic | Safety critical |
| SQL execution | Deterministic | Correctness critical |
| RAG retrieval type | LLM | Fuzzy classification benefit |
| Intent routing | LLM | Core agent decision |
| SQL generation | LLM | Flexibility + schema grounding |
| Answer synthesis | Mixed | Template-based + LLM fallback |
| Unknown intent | LLM | Generative response |

### 13.3 Memory & Conversation Continuity

**Conversation Memory System:**
- sử dụng Qdrant vector store de luu tru conversation history
- Singleton `ConversationMemoryStore` với thread safety
- Semantic similarity de phat hien implicit follow-ups
- Compaction mechanism de quan ly dung luong

**Continuity Detection:**
- `detect_continuity_node` kiem tra cac truy van lien tiep trong cung thread
- Trich xuat context tu cac lan hoi truoc de cai thien hieu qua
- Giam so lan LLM phai giai thich lai cac khai niem da được trao doi

### 13.4 Plan-and-Execute Architecture (V2)

**Parallel Fan-out with Send API:**
- `task_planner` phan tích query thanh cac subtasks doc lap
- `Send` API tao fan-out đến cac `sql_worker` thuc hien song song
- `operator.add` accumulation cho fan-in ket qua
- "Nested sequential within parallel" pattern cho visualization dependency

**Scalability Benefits:**
- N queries doc lap chay song song thay vi lan luot
- Better resource utilization cho cac tasks khong lien quan
- Improved response time cho complex multi-part queries

### 13.3 Token Counter Embedding vs External Embeddings

RAG index dùng bag-of-words token counter thay vi external embedding model:
- **Pros:** Không cần API key, không tốn chi phí, fast
- **Cons:** Không bắt được semantic similarity, không hiệu qua cho synonyms

### 13.4 TypedDict total=False

`AgentState` dùng `TypedDict(total=False)` để cho phep optional keys:
- LangGraph TypedDict state không yêu cầu tất cả keys phải có
- Avoids runtime errors từ key missing
- Trade-off: Type checker không bắt được missing keys at compile time

---

## 14. File Structure

```
backend/
├── main.py               # FastAPI app factory, startup events, seeding
├── routers/
│   ├── __init__.py       # Router imports
│   ├── health.py         # Health check endpoints
│   ├── query.py          # Query endpoints (POST, upload, streaming SSE)
│   ├── threads.py        # Thread/conversation management
│   └── evals.py          # Eval endpoints
├── models/
│   ├── __init__.py       # Model imports
│   ├── requests.py       # Pydantic request models
│   └── responses.py      # Pydantic response models
├── services/
│   ├── __init__.py       # Service imports
│   ├── agent_service.py  # Async wrapper around run_query()
│   └── sse_service.py    # Server-Sent Events streaming
└── utils/
    ├── __init__.py       # Utility imports
    └── serialization.py  # Bytes/base64 serialization helpers

app/
├── graph/
│   ├── state.py          # AgentState, GraphInput/OutputState, Intent, Confidence types
│   ├── graph.py          # build_sql_v1_graph(), build_sql_v2_graph(), _instrument_node()
│   ├── edges.py          # route_after_* conditional edges, Send API fan-out
│   ├── nodes.py          # All 12+ nodes implementation
│   ├── sql_worker_graph.py # Nested subgraph for parallel SQL execution
│   ├── standalone_visualization.py # E2B-based visualization worker
│   ├── continuity.py     # Conversation continuity detection
│   ├── context_resolver.py # Context resolution logic
│   ├── error_classifier.py # Error classification system
│   └── run_config.py     # RunConfig, new_run_config(), to_langgraph_config()
├── tools/
│   ├── get_schema.py     # list_tables, describe_table, get_schema_overview
│   ├── validate_sql.py   # validate_sql() with SQLValidationResult
│   ├── query_sql.py      # query_sql() execution
│   ├── retrieve_metric_definition.py  # Wrapper
│   ├── retrieve_business_context.py  # Wrapper
│   ├── dataset_context.py # Row counts, date ranges, samples
│   ├── csv_validator.py  # CSV validation tools
│   ├── csv_profiler.py   # CSV profiling tools
│   ├── auto_register.py  # CSV auto-registration pipeline
│   ├── visualization.py  # E2BVisualizationService
│   └── mcp_client.py     # call_mcp_tool(), persistent MCP connection
├── memory/
│   ├── __init__.py       # Memory module imports
│   ├── conversation_store.py # Conversation memory with Qdrant integration
│   ├── context_store.py  # Context persistence layer
│   └── qdrant_client.py  # Vector store client
├── prompts/
│   ├── manager.py        # PromptManager with Langfuse + local fallback
│   ├── router.py         # ROUTER_PROMPT_DEFINITION
│   ├── sql.py            # SQL_PROMPT_DEFINITION
│   ├── context_detection.py # Context detection prompts
│   ├── synthesis.py      # Synthesis prompts
│   └── analysis.py       # ANALYSIS_PROMPT_DEFINITION
├── rag/
│   ├── index_docs.py     # build_local_index(), query_index() with cosine similarity
│   └── retriever.py      # retrieve_metric_definition(), retrieve_business_context()
├── observability/
│   ├── tracer.py         # RunTracer, LangfuseAdapter, NodeScope
│   └── schemas.py        # NodeTraceRecord, RunTraceRecord, FailureCategory
├── llm/
│   └── client.py         # LLMClient with chat_completion, cost estimation
├── config.py             # Settings dataclass, load_settings()
├── logger.py             # Loguru logger setup
└── main.py               # sync run_query(), main() CLI entry

evals/
├── runner.py             # Eval runner with parallel execution
├── case_contracts.py     # EvalCase dataclass, load_cases_jsonl()
├── groundedness.py       # _keyword_groundedness(), _llm_evaluate_groundedness()
├── cases/
│   ├── domain_cases.jsonl    # 36 bilingual domain cases
│   ├── dev/spider_dev.jsonl
│   ├── test/spider_test.jsonl
│   ├── dev/movielens_*_dev.jsonl
│   └── test/movielens_*_test.jsonl
├── metrics/
│   ├── spider_exact_match.py # SQL component comparison
│   ├── execution_accuracy.py # Execute & compare results
│   └── llm_judge.py          # LLM-as-judge evaluation
└── reports/               # traces.jsonl, summary_*.json/md, per_case_*.jsonl

mcp_server/
└── server.py              # FastMCP server with tool definitions

streamlit_app.py           # Thin client with SSE streaming

docs/
├── research/rag/          # RAG source documents
└── thangquang09/
    ├── CLAUDE.md          # Owner priority docs
    ├── overview.md
    ├── implementation_todo.md
    └── system_design.md    # This file
```

---

## 15. Configuration

### 15.1 Environment Variables

```bash
# LLM
LLM_API_URL=https://.../v1/chat/completions
LLM_API_KEY=sk-...
DEFAULT_ROUTER_MODEL=gh/gpt-4o-mini
DEFAULT_SYNTHESIS_MODEL=gh/gpt-4o
DEFAULT_PLANNER_MODEL=gh/gpt-4o

# Database
SQLITE_DB_PATH=data/warehouse/analytics.db

# Backend
BACKEND_PORT=8001
BACKEND_CORS_ORIGINS=http://localhost:8501,*  # Streamlit + wildcard for dev
BACKEND_RELOAD=false  # Enable for development

# Memory
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION_NAME=conversation_memory

# Observability
TRACE_JSONL_PATH=evals/reports/traces.jsonl
ENABLE_LANGFUSE=true
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...

# MCP
ENABLE_MCP_TOOL_CLIENT=false
MCP_TRANSPORT=streamable-http
MCP_HTTP_URL=http://127.0.0.1:8000/mcp

# Eval
ENABLE_LLM_SQL_GENERATION=true
PROMPT_CACHE_TTL_SECONDS=300

# E2B (Visualization)
E2B_API_KEY=  # Optional - if not set, visualization features disabled
```

### 15.2 Streaming & SSE Configuration

The system supports real-time progress feedback via Server-Sent Events:

- **Backend streaming endpoint**: `GET /query/stream` in `backend/routers/query.py`
- **Frontend integration**: Streamlit uses `EventSource` to receive real-time updates
- **Event types**: `started`, `node_completed`, `result`, `error`
- **Progress tracking**: Each node completion fires an event with status update

---

## 16. Recent Changes (2026-03-31)

### Generalization Sprint

- Removed `_fallback_route_intent()` hardcoded keyword matching → fully LLM-driven
- Removed `_rule_based_sql()` hardcoded SQL patterns → fully LLM-driven  
- Added `_llm_decide_retrieval_type()` for RAG type selection
- Added `_llm_synthesize_fallback()` for unknown intent handling

### Current Status

- **Routing accuracy:** 100% (domain eval, 12 cases)
- **Tool path accuracy:** 100%
- **SQL validity rate:** 100%
- **Answer format validity:** 100%
- **Groundedness pass rate:** ~17% (known issue: keyword-based eval vs LLM synthesis - see `EVAL_FIX_TASK.md`)
