# Hướng Dẫn Ôn Luyện Phỏng Vấn - DA Agent Lab

> **Tài liệu này được viết dạng hội thoại tự nhiên tiếng Việt để bạn ôn luyện trước phỏng vấn về DA Agent Lab project.**

---

## Phần 1: Tổng Quan Project

### Câu hỏi: "Hãy nói về project của bạn"

**Cách trả lời:**

Project của tôi tên là **DA Agent Lab** — một hệ thống agent thông minh được xây dựng trên nền tảng LangGraph. Nó được thiết kế để trả lời các câu hỏi về dữ liệu kinh doanh bằng cách chuyển đổi ngôn ngữ tự nhiên thành SQL queries và tạo ra các visualizations động.

Bản chất của project là một **constrained agent** — nghĩa là LLM không được tự do thực hiện bất kỳ hành động nào, mà chỉ có thể gọi các tools mà tôi đã định nghĩa trước. Điều này đảm bảo an toàn và tính kiểm soát.

**Tại sao tôi xây dựng nó:**

Đây là một portfolio project để demonstrate khả năng của tôi trong AI application prototyping, prompt engineering, và system design. Project này mapping trực tiếp với các yêu cầu công việc AI/Agent Engineer:
- Xây dựng multi-agent applications với LangGraph
- Thiết kế prompt và optimize LLM behavior
- Implement agentic tools với MCP (Model Context Protocol)
- Xây dựng evaluation frameworks
- Thiết kế observability system

**Architecture chính:**

Project hiện có 2 versions của graph:
- **V1**: Linear sequential (dễ debug, dùng làm baseline)
- **V2**: Plan-and-Execute với parallel processing (production default, scalable hơn)

Ngoài ra, tôi cũng xây dựng FastAPI backend để thay thế monolithic Streamlit, cho phép streaming real-time feedback và scale tốt hơn.

---

## Phần 2: Kiến Trúc Chi Tiết

### Câu hỏi: "Giải thích kiến trúc của bạn"

**Cách trả lời:**

Kiến trúc được chia thành 3 layers chính:

**Layer 1: Entry Points**
- CLI (`python -m app.main "query"`) — để test quick
- FastAPI backend (`backend/main.py`) — production
- Streamlit thin client — web UI
- MCP Server — cho các tools có thể dùng lại

**Layer 2: LangGraph Orchestration**

LangGraph là một framework cho phép tôi xây dựng directed graph của các nodes. Mỗi node là một Python function. Tôi xây dựng 2 graph versions:

- **V1 graph** (Linear):
  ```
  detect_context_type 
    → process_uploaded_files (nếu có CSV)
    → inject_session_context (từ conversation memory)
    → detect_continuity (phát hiện follow-ups)
    → route_intent (LLM quyết định: sql/rag/mixed/unknown)
    → [conditional edges]:
        - sql/mixed: get_schema → generate_sql → validate_sql → execute_sql → analyze_result
        - rag: retrieve_context_node
        - unknown: synthesize_answer
    → synthesize_answer
    → capture_action_node
    → compact_and_save_memory
  ```

- **V2 graph** (Plan-and-Execute):
  ```
  [Các steps giống V1 cho đến route_intent]
    → task_planner (phân tích query thành N subtasks)
    → [Send API fan-out]:
        - sql_worker × N (chạy song song)
        - standalone_visualization (tạo chart)
    → [operator.add accumulation]:
        - aggregate_results (gom kết quả)
    → [tiếp tục như V1]
  ```

**Layer 3: Core Components**

- **Tools**: get_schema, query_sql, validate_sql, retrieve_*, visualization, csv_*
- **Memory System**: Qdrant vector store cho conversation continuity
- **Prompts**: Router, SQL generator, Task planner, Synthesis — all Langfuse-backed với local fallback
- **Observability**: JSONL tracing + Langfuse adapter
- **Evaluation**: Parallel eval runner với gate thresholds

**Tại sao thiết kế như vậy:**

1. **Constrained agent pattern**: LLM chỉ gọi predefined tools → safer, more predictable
2. **Deterministic vs Fuzzy separation**: SQL validation (deterministic), LLM routing (fuzzy) → clear boundaries
3. **Plan-and-Execute**: Cho phép xử lý song song → latency thấp hơn
4. **Memory & Continuity**: Context từ trò chuyện trước → chatbot experience tốt hơn

---

## Phần 3: Technical Deep Dives

### Câu hỏi 3.1: "Làm sao bạn đảm bảo SQL safety?"

**Cách trả lời:**

SQL safety là critical vì user có thể inject malicious queries. Tôi có 2 layers của defensive programming:

**Layer 1: Regex Validation (Pre-execution)**

```python
FORBIDDEN_PATTERNS = [
    r"\bINSERT\b", r"\bUPDATE\b", r"\bDELETE\b",
    r"\bDROP\b", r"\bALTER\b", r"\bTRUNCATE\b",
    # ... etc
]

READ_ONLY_PATTERN = r"^\s*(SELECT|WITH)\b"
```

Nếu SQL chứa bất kỳ từ khóa nguy hiểm nào, validation sẽ reject luôn. Không có exception.

**Layer 2: Table/Column Validation (Runtime)**

```python
# Extract tất cả table references
TABLE_PATTERN = r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)\b"
tables = re.findall(TABLE_PATTERN, sql)

# Check từng table có tồn tại trong SQLite schema không
for table in tables:
    if table not in available_tables:
        return SQLValidationResult(is_valid=False, reasons=[...])
```

**Flow trong graph:**

```
generate_sql → validate_sql_node → [is_valid? YES → execute_sql_node
                                              NO → retry generate_sql (max 2x)]
```

Nếu validation fail, LLM nhận error message và retry. Nếu fail 2 lần thì dump sang RAG hoặc unknown intent.

**Tại sao 2 layers:**
- Layer 1: Catch obvious attacks (SQL injection patterns)
- Layer 2: Catch LLM hallucinations (table names bịa)
- Combination: Very hard để vượt qua

---

### Câu hỏi 3.2: "Giải thích Plan-and-Execute architecture"

**Cách trả lời:**

Đây là pattern mạnh mẽ để handle complex, multi-part queries.

**Problem**: 
User hỏi "DAU 7 ngày gần đây như thế nào và compare với 7 ngày trước đó có biểu đồ không?"

Đây thực chất là 2 queries độc lập:
- Query 1: Lấy DAU 7 ngày gần đây
- Query 2: Lấy DAU 7 ngày trước đó
- Task 3: Tạo biểu đồ so sánh

Nếu chạy sequential, phải chờ query 1 xong rồi query 2 rồi visualization. Total latency = Query1_latency + Query2_latency + Viz_latency (~10-15 giây).

**Solution — Send API Fan-out:**

`task_planner` nhận query, phân tích, output:
```json
{
  "execution_mode": "parallel",
  "tasks": [
    {"task_id": "t1", "sql": "SELECT ... [7 days recent]", "requires_visualization": false},
    {"task_id": "t2", "sql": "SELECT ... [7 days before]", "requires_visualization": false},
    {"task_id": "t3", "requires_visualization": true, "data": ...}
  ]
}
```

LangGraph's `Send` API:
```python
# edges.py
def route_after_planning(state) -> list[Send]:
    tasks = state["task_plan"]
    sends = []
    for task in tasks:
        sends.append(Send("sql_worker", task))
    return sends  # ← Fan-out, all run in parallel
```

Mỗi task chạy qua `sql_worker` subgraph riêng (get_schema → generate_sql → validate → execute → analyze).

Khi tất cả tasks hoàn thành, `operator.add` accumulation:
```python
task_results: Annotated[list[TaskState], operator.add]
```

Kết quả được gom lại ở `aggregate_results`, rồi toàn bộ tính toán được synthesize thành 1 câu trả lời cuối cùng.

**Latency improvement:**
- Nếu Query 1 = 3s, Query 2 = 3s, Viz = 4s
- Sequential: 3 + 3 + 4 = 10s
- Parallel: max(3, 3, 4) = 4s (LLM synthesis overhead + small latency)

**Tricky part — Nested Sequential within Parallel:**

Visualization cần SQL result từ cùng task. Nếu visualization chạy song song với SQL (ở 2 workers khác nhau), visualization sẽ fail vì không có data.

**Solution**: Embed visualization node bên trong sql_worker subgraph:
```python
# sql_worker_graph.py
get_schema → generate_sql → validate_sql → execute_sql → analyze_result
                                                              ↓
                                        [if requires_visualization]:
                                              visualization_node
```

Vậy SQL result có sẵn khi visualization node chạy.

**Benefit của architecture này:**
- Independent tasks chạy song song ✓
- Task dependencies (SQL → visualization) được handle đúng ✓
- Complex multi-part queries xử lý efficient ✓

---

### Câu hỏi 3.3: "Làm sao bạn handle large result sets từ SQL?"

**Cách trả lời:**

Một vấn đề thường gặp trong Text-to-SQL: nếu query trả về 10,000 rows, mà bạn pass toàn bộ rows vào LLM synthesis prompt, bạn sẽ bị HTTP 400 (context overflow).

**Two-Tier Data State Pattern:**

Tôi tách dữ liệu thành 2 tiers:

**Tier 1: Raw Data (cho deterministic processing)**
```python
sql_result: dict = {
    "rows": [
        {"date": "2024-01-01", "dau": 15000},
        {"date": "2024-01-02", "dau": 15500},
        ...  # 10,000 rows
    ],
    "row_count": 10000,
    "columns": ["date", "dau"],
    "latency_ms": 245
}
```

**Tier 2: Compressed Analysis (cho LLM synthesis)**
```python
analysis_result: dict = {
    "summary": "DAU tăng từ 15,000 lên 18,500 trong 7 ngày",
    "trend": "upward",
    "trend_percentage": 23.3,
    "anomalies": [
        {"date": "2024-01-05", "dau": 12000, "reason": "platform outage"}
    ]
}
```

**Flow:**

```
execute_sql_node → [raw 10k rows in state]
    ↓
analyze_result → [LLM/deterministic processing]:
    - Calculate trend (up/down/flat)
    - Extract anomalies
    - Get summary statistics
    → [compressed analysis_result]
    ↓
synthesize_answer → [nhận analysis_result, KHÔNG nhận raw rows]
    - Prompt bao gồm: summarized data từ analysis_result
    - LLM tạo natural language answer từ summary
```

**Tại sao hiệu quả:**
- Raw 10k rows = ~50KB text = context overflow
- Compressed analysis = ~500 bytes = safe
- Deterministic analysis không phụ thuộc LLM → consistent

---

### Câu hỏi 3.4: "Conversation memory hoạt động thế nào?"

**Cách trả lời:**

Hầu hết SQL agents không có memory giữa các turns. Nếu bạn hỏi:
- Turn 1: "DAU hôm qua là bao nhiêu?"
- Turn 2: "Nó so với tuần trước như thế nào?"

Agent ở Turn 2 không biết "nó" là DAU (vì không nhớ Turn 1).

**Conversation Memory System tôi xây:**

**Storage:**
- Qdrant vector store (persistent)
- `ConversationMemoryStore` singleton (thread-safe)
- Per-thread memory isolation (mỗi conversation có thread_id riêng)

**Nodes liên quan:**
- `inject_session_context`: Lấy conversation history từ Qdrant
- `detect_continuity_node`: Phát hiện implicit follow-ups
- `capture_action_node`: Lưu current turn vào memory
- `compact_and_save_memory`: Nén memory, persist vào Qdrant

**Example flow:**

```
Turn 1: "DAU hôm qua là bao nhiêu?"
  → route_intent: sql
  → execute_sql: SELECT dau FROM daily_metrics WHERE date = yesterday
  → Result: 15,000
  → capture_action_node: Lưu {query: "...", answer: "15,000", date: "2024-01-07"}
  → Memory: [[turn1_embedding, turn1_text]]

Turn 2: "Nó so với tuần trước như thế nào?"
  → inject_session_context: Query Qdrant:
       "Nó so với tuần trước" → [semantic search] → "nó" ~ "DAU"
       Memory found: {turn1: "DAU hôm qua là 15,000"}
  → detect_continuity_node: "Continuity detected! 'nó' = DAU"
  → state.session_context = "Từ trò chuyện trước: DAU hôm qua là 15,000"
  → route_intent: sql (vẫn cần SQL query)
  → SQL generation prompt include session_context
  → LLM: "So sánh DAU hôm qua (15,000) với DAU tuần trước..."
```

**Benefit:**
- Multi-turn conversations feel natural
- LLM có context từ trước → không cần user repeat
- Implicit follow-ups work correctly

---

### Câu hỏi 3.5: "Làm sao bạn prompt engineer LLM?"

**Cách trả lời:**

Prompt engineering là art + science. Tôi có few-shot examples, structured output, và fallbacks.

**1. Few-Shot Prompting (Task Planner)**

Task planner phải output JSON:
```json
{
  "execution_mode": "parallel",
  "tasks": [{...}, {...}]
}
```

Nếu không có few-shot examples, LLM sẽ output free-form text, không parse được. Prompt tôi:

```
You are a task decomposer. Analyze the query and break it into parallelizable tasks.

EXAMPLE:
User: "DAU 7 days and next week predictions"

Your output MUST be ONLY valid JSON like:
{
  "execution_mode": "parallel",
  "tasks": [
    {"task_id": "t1", "description": "Fetch DAU for past 7 days"},
    {"task_id": "t2", "description": "Predict DAU for next week"}
  ]
}

No markdown. No explanations. JSON only.
```

**2. Structured JSON Output (Router)**

Router phải output intent (sql/rag/mixed/unknown):

```
# Router prompt template
You are an intent classifier for Data Analyst Agent.

Classify the query into EXACTLY ONE intent:
- sql: needs numeric values, trends, comparisons from data
- rag: needs definitions, rules, business context
- mixed: needs both data and business context
- unknown: casual questions, help requests, not data-related

Return ONLY JSON:
{"intent":"sql|rag|mixed|unknown","reason":"short explanation"}

No markdown. Only JSON.
```

**3. Self-Correction Loop (SQL Generation)**

SQL generation có error handling:

```
You are a SQL generator. Generate a SELECT query.

Schema:
- daily_metrics: date, dau, retention_d1, revenue
- videos: video_id, watch_time, retention_rate

If previous SQL failed with error, fix it:
[previous_error: "no such column: 'dau_7day'"]

Generate correct SQL now. Use ONLY available columns.
```

Nếu generate fail, error message inject vào prompt, LLM retry (max 2x).

**4. Langfuse Prompt Management**

Prompts không hardcoded, lấy từ Langfuse (A/B testing ready):

```python
# prompts/manager.py
manager = PromptManager()
router_prompt = manager.get_prompt(
    name="router",
    version="latest",  # Langfuse picks version
    fallback=ROUTER_PROMPT_DEFINITION  # Local template as fallback
)
```

TTL cache (300s) để tránh network overhead mỗi request.

**5. Anti-Hallucination Rules**

SQL prompt rõ ràng:
```
FORBIDDEN:
- Do NOT use columns not in schema
- Do NOT use column aliases without definition
- Do NOT use unknown functions
- ALWAYS add LIMIT 1000 for safety
```

RAG retrieval explicit về retrieval type (metric definition vs business context).

---

### Câu hỏi 3.6: "Tại sao bạn chọn LangGraph thay vì LangChain LCEL hay CrewAI?"

**Cách trả lời:**

Mỗi framework có trade-offs. Tôi chọn LangGraph vì:

**1. Explicit State Management**
- LCEL: Functional chaining (f ∘ g), state ẩn → khó debug
- CrewAI: Agent team abstraction, state ẩn → black box
- LangGraph: Explicit `AgentState` TypedDict → tôi thấy chính xác cái gì trong state lúc nào

```python
# LangGraph — Explicit
def my_node(state: AgentState) -> dict:
    # I know exactly what's in state, what I can update
    return {"intent": "sql", "tool_history": [...]}

# LCEL — Functional
output = (
    router | format_history | selector | executor
)  # Chain opaque, hard to inspect intermediate states
```

**2. Conditional Edges**
- LCEL: Có condition, nhưng awkward
- LangGraph: First-class conditional edges

```python
# LangGraph — Clear
builder.add_conditional_edges(
    "route_intent",
    route_after_intent,  # Function return next node
    {
        "sql": "get_schema",
        "rag": "retrieve_context",
        "unknown": "synthesize_answer"
    }
)
```

**3. Subgraph Support**
- LCEL: Mỗi step là function, không clear hierarchy
- LangGraph: Có subgraphs (sql_worker_graph nested inside main graph)

```python
# LangGraph — Hierarchical
sql_worker_graph = StateGraph(TaskState, ...)
sql_worker_graph.add_node("get_schema", ...)
# ... compose nodes

main_graph = StateGraph(AgentState, ...)
main_graph.add_node("sql_worker", sql_worker_graph.compile())
```

**4. Retry Policies**
- LangGraph built-in retry policy per node

```python
builder.add_node(
    "generate_sql",
    generate_sql,
    retry_policy=RetryPolicy(max_attempts=2)
)
```

**5. Checkpointing & Persistence**
- LangGraph: Built-in memory checkpointer cho multi-turn

```python
graph.compile(checkpointer=InMemorySaver())
graph.invoke(input, config={"configurable": {"thread_id": "user_123"}})
```

**6. Observability Integration**
- LangGraph node instrumenting dễ hơn (decorator pattern)
- I can wrap each node để auto-trace

**Trade-offs:**
- Steeper learning curve (explicit state modeling)
- More boilerplate than LCEL
- But: Ultimate control, debuggability, production readiness

Tôi choose LangGraph vì tôi value explicit state + debuggability + production readiness hơn là quick prototyping.

---

## Phần 4: Challenges & Problem Solving

### Câu hỏi 4.1: "Bug khó nhất bạn gặp?"

**Cách trả lời:**

Bug khó nhất là **"Visualization Data Dependency Trap"** trong V2 parallel architecture.

**Problem:**

V2 graph có parallel fan-out: mỗi SQL task chạy độc lập via `Send` API.

```
task_planner → Send(sql_worker, task1)
            → Send(sql_worker, task2)
            → Send(standalone_visualization, task)
```

Nhưng visualization cần data từ SQL execution. Nếu visualization chạy song song ở worker khác, nó sẽ fail vì không có data:

```
task1 (parallel):
  - get_schema → generate_sql → validate → execute → result
  
task_visualization (parallel, cùng lúc):
  - need_data_from_task1? → NOT AVAILABLE YET → CRASH
```

**Solution — Nested Sequential within Parallel:**

Embed visualization inside sql_worker subgraph:

```python
# sql_worker_graph.py (TaskState scope, not AgentState)
def build_sql_worker_graph():
    graph = StateGraph(TaskState)
    graph.add_node("get_schema", get_schema)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("validate_sql", validate_sql)
    graph.add_node("execute_sql", execute_sql)
    graph.add_node("analyze_result", analyze_result)
    graph.add_node("visualization", visualization_node)  # ← INSIDE
    
    # Sequential edges
    graph.add_edge("get_schema", "generate_sql")
    graph.add_edge("generate_sql", "validate_sql")
    graph.add_edge("validate_sql", "execute_sql")
    graph.add_edge("execute_sql", "analyze_result")
    
    # Conditional: visualization chỉ chạy nếu requires_visualization=True
    graph.add_conditional_edges(
        "analyze_result",
        lambda state: "visualization" if state["requires_visualization"] else "END",
        {"visualization": "visualization", "END": END}
    )
    graph.add_edge("visualization", END)
    return graph.compile()
```

Điều này đảm bảo:
- SQL execution và visualization **cho cùng task** là sequential (đúng dependency order)
- **Khác tasks** vẫn chạy song song (via Send fan-out)

**Architecture:** "Nested sequential within parallel"

Bây giờ visualization có data vì nó chạy sau execute ở cùng worker.

**Why hard to fix:**

1. Không phải obvious lỗi — system không crash, nhưng visualization result empty
2. Tracing difficult — task1 xong, task_visualization chạy, nhưng dữ liệu không match
3. Yêu cầu redesign graph hierarchy — không thể quick fix ở node level

**Lesson learned:**

Trong parallel architectures, bắt buộc cân nhắc data dependencies sẽ. Không thể fan-out tất cả tasks mà không check dependencies.

---

### Câu hỏi 4.2: "Gặp vấn đề gì với migration từ Streamlit sang FastAPI?"

**Cách trả lời:**

Monolithic Streamlit rất tiện lúc prototype, nhưng khi scale:
- Mỗi user connection = 1 process (heavy)
- Không thể streaming progress real-time (Streamlit rerun paradigm)
- State management awkward khi có server requests

**Challenges:**

1. **Async/Threading**
   - LangGraph graph.invoke() là blocking (chạy ~7-10s)
   - Streamlit runs inside asyncio event loop
   - Solution: `loop.run_in_executor()` để offload LangGraph call vào thread pool

```python
# backend/services/agent_service.py
loop = asyncio.get_event_loop()
payload = await loop.run_in_executor(
    None,
    lambda: run_query(query=...)  # Blocking call
)
```

2. **File Upload Serialization**
   - Streamlit passes bytes directly
   - FastAPI receives bytes qua JSON → need base64 encoding
   - Solution: serialize bytes to base64 trong request, deserialize ở backend

```python
# Request model
class FileData(BaseModel):
    name: str
    data: str  # base64-encoded

# Backend
if isinstance(raw, str):
    raw = base64.b64decode(raw)  # Convert back to bytes
```

3. **SSE Streaming**
   - Người dùng muốn thấy progress real-time (node completion events)
   - Solution: `EventSourceResponse` từ sse_starlette
   - Mỗi node completion, fire event: `data: {"node": "route_intent", "status": "completed"}`

```python
# backend/routers/query.py
@router.get("/stream")
async def query_stream(q: str, ...):
    return EventSourceResponse(
        stream_query_events(query=q, ...),
        media_type="text/event-stream"
    )

# frontend (Streamlit)
from sseclient import SSEClient
with st.spinner("Agent thinking..."):
    for event in SSEClient(f"{BACKEND_URL}/query/stream?q=..."):
        if event.event == "node_completed":
            st.write(f"✓ {event.data}")
```

4. **Thread Safety**
   - Multiple concurrent requests → concurrent LangGraph invocations
   - ContextVar cho RunTracer (isolated per thread) ✓
   - SQLite check_same_thread=False cho memory store ✓
   - graph.invoke() creates fresh graph instance per call ✓

**Benefits của migration:**

- ✓ Thin client (Streamlit) không phải xử lý heavy logic
- ✓ Backend scalable — có thể có multiple backend instances
- ✓ Real-time streaming feedback (SSE)
- ✓ Can call backend từ CLI, HTTP client, MCP client, etc.

---

## Phần 5: Evaluation & Metrics

### Câu hỏi 5.1: "Bạn đo lường performance thế nào?"

**Cách trả lời:**

Evaluation là first-class citizen trong project. Không phải tùy tiện — có automated gates.

**Eval Framework:**

```
evals/
├── runner.py              # Parallel case executor
├── case_contracts.py      # EvalCase dataclass
├── metrics/
│   ├── spider_exact_match.py    # SQL component comparison
│   ├── execution_accuracy.py    # Execute & compare results
│   └── llm_judge.py             # LLM-as-judge for answer quality
└── cases/
    ├── domain_cases.jsonl        # 36 bilingual domain cases
    ├── dev/spider_dev.jsonl      # Spider benchmark dev set
    └── test/spider_test.jsonl    # Spider benchmark test set
```

**Eval Case Contract:**

```json
{
  "id": "case_001",
  "suite": "domain",
  "query": "DAU 7 ngày gần đây có giảm không?",
  "expected_intent": "sql",
  "expected_tools": ["get_schema", "query_sql"],
  "should_have_sql": true,
  "gold_sql": "SELECT date, dau FROM daily_metrics ORDER BY date DESC LIMIT 7",
  "expected_keywords": ["giảm", "7 ngày"],
  "target_db_path": "data/warehouse/domain_eval.db"
}
```

**Metrics Computed:**

```python
# Per-case
CaseResult {
    routing_correct: bool  # Predicted intent == expected intent
    sql_valid: bool        # SQL passed validation
    tool_path_correct: bool  # Used expected tools
    execution_match: bool  # Execution result matched expected
    groundedness_pass: bool  # Answer grounded in data
    answer_quality_score: float  # LLM judge score
    latency_ms: float
}

# Aggregate (summary)
{
    "routing_accuracy": 0.95,
    "sql_validity_rate": 0.88,
    "tool_path_accuracy": 0.92,
    "execution_accuracy": 0.85,
    "groundedness_pass_rate": 0.78,
    "answer_quality_score": 0.81,
    "avg_latency_ms": 5200
}
```

**Gate Thresholds (CI/CD gates):**

```python
GATE_THRESHOLDS = {
    "routing_accuracy": 0.90,        # Block if <90%
    "sql_validity_rate": 0.90,
    "tool_path_accuracy": 0.95,
    "answer_format_validity": 1.00,
    "groundedness_pass_rate": 0.70,
}
```

Nếu bất kỳ metric nào drop dưới threshold → CI block (prevent regression).

**Run eval:**

```bash
# Domain suite (fast, 36 cases)
uv run python -m evals.runner --suite domain

# Spider dev set (200 sampled cases)
uv run python -m evals.runner --suite spider --split dev

# With enforcement
uv run python -m evals.runner --suite domain --enforce-gates
```

**Output:**

```
evals/reports/
├── latest_summary.json       # Aggregate metrics
├── latest_summary.md         # Human-readable
└── per_case_{timestamp}.jsonl  # Per-case details
```

**Evaluator Types:**

1. **Routing Accuracy**: Is predicted intent correct?
2. **SQL Validity**: Does SQL pass validation?
3. **Execution Accuracy**: Does SQL return same result as gold_sql?
4. **Spider Exact Match**: Component-level SQL comparison (SELECT, FROM, WHERE, etc.) — industry benchmark
5. **LLM Judge**: Does answer quality meet expectations?
6. **Groundedness**: Is every claim supported by data?

---

### Câu hỏi 5.2: "Metric nào khó nhất để đạt?"

**Cách trả lời:**

**Groundedness** là khó nhất, vì nó bao gồm semantic matching.

**Problem:**

Eval case expects:
```json
{
  "query": "DAU hôm qua thế nào?",
  "expected_keywords": ["DAU", "hôm qua", "15000"]
}
```

LLM synthesis trả: "Chỉ số DAU ngày hôm qua đạt 15 ngàn người dùng hoạt động."

**Metrics:**
- ✓ DAU (exact match)
- ✓ hôm qua (fuzzy match)
- ✗ 15000 (LLM wrote "15 ngàn" không "15000")

Traditional keyword matching fails do:
- Synonyms (DAU = chỉ số DAU = unique users)
- Number formatting (15000 = 15 ngàn = 15k)
- Language variations

**Solution — 2-Tier Groundedness:**

1. **Keyword-based** (fast): Simple keyword/substring matching
2. **LLM-based** (fallback): Use LLM to check if claim is supported

```python
def evaluate_groundedness(answer, retrieved_data):
    claims = extract_claims(answer)  # NLP to extract factual claims
    
    for claim in claims:
        # Tier 1: Regex keyword match
        if keyword_match(claim, retrieved_data):
            continue
        
        # Tier 2: LLM semantic match
        is_supported = llm_check_support(claim, retrieved_data)
        if not is_supported:
            unsupported_claims.append(claim)
    
    groundedness_score = (len(claims) - len(unsupported_claims)) / len(claims)
    return groundedness_score
```

**Current threshold:** 0.70 (70% claims must be grounded)

**Why hard:**
- Mỗi domain có different terminology
- Number formatting varies (15,000 vs 15 ngàn vs 15k)
- Semantic equivalence is fuzzy
- LLM evaluation có bias của riêng nó

---

## Phần 6: Tools & MCP Integration

### Câu hỏi 6.1: "Tools là gì? Tại sao MCP important?"

**Cách trả lời:**

**Tools** là functions mà agent có thể gọi. Mỗi tool:
- Có explicit input schema (type-hinted)
- Có explicit output schema (return type)
- Có error handling (return Result, không throw)
- Có side-effects (query DB, call API, etc.)

**Examples in project:**

```python
# app/tools/get_schema.py
def get_schema(db_path: str | None = None) -> str:
    """
    Returns JSON schema of SQLite database.
    
    Args:
        db_path: Path to SQLite DB (optional, defaults to env SQLITE_DB_PATH)
    
    Returns:
        JSON string with table/column metadata
    
    Raises:
        FileNotFoundError: If db_path does not exist
    """
    ...

# app/tools/query_sql.py
def query_sql(sql: str, row_limit: int = 1000, db_path: str | None = None) -> dict:
    """
    Execute read-only SQL query.
    
    Args:
        sql: SELECT or WITH query only
        row_limit: Max rows to return (default 1000)
        db_path: Path to SQLite DB (optional)
    
    Returns:
        {
            "rows": [...],
            "row_count": int,
            "columns": [...],
            "latency_ms": float
        }
    """
    ...
```

**Why explicit schemas matter:**

1. **Reusability**: Tool có thể dùng từ CLI, HTTP, MCP, LLM agent
2. **Debuggability**: Có thể trace exactly what inputs/outputs là
3. **Testing**: Unit test dễ hơn (functional interface)
4. **Documentation**: Schema itself is docs

**MCP (Model Context Protocol):**

MCP là standard cho agentic tools. Nó allow:
- LLM (Claude, GPT, etc.) gọi tools qua standardized interface
- Tools published qua HTTP, stdio, WebSocket
- Interoperability (Claude dùng tools từ many servers)

**MCP Server tôi xây:**

```python
# mcp_server/server.py
from fastmcp import FastMCP

mcp = FastMCP("DA Agent Lab")

@mcp.tool()
def get_schema(db_path: str | None = None) -> str:
    """Get SQLite schema"""
    return app.tools.get_schema(db_path)

@mcp.tool()
def query_sql(sql: str, row_limit: int = 1000) -> dict:
    """Execute SQL query"""
    return app.tools.query_sql(sql, row_limit)

# ... more tools

mcp.run(transport="stdio")  # or "http"
```

**Running MCP server:**

```bash
python -m mcp_server.server  # stdio mode (sync call)
# or
MCP_TRANSPORT=streamable-http python -m mcp_server.server  # HTTP mode (persistent)
```

**Why important:**

1. **Standardization**: Tools không bị lock vào framework nào
2. **Reuse**: Cùng tool dùng được ở CLI, Streamlit, HTTP API, MCP
3. **Interview value**: Shows understanding of agentic tool standards
4. **Future-proof**: Nếu dùng Claude thay vì OpenAI, tools vẫn work

---

## Phần 7: Observability & Tracing

### Câu hỏi 7.1: "Bạn trace requests thế nào?"

**Cách trả lời:**

Observability là bắt buộc để debug. Tôi có 2-layer tracing:

**Layer 1: Run-level Tracing**

```python
# app/observability/tracer.py
class RunTracer:
    def __init__(self, run_id: str, thread_id: str, query: str):
        self.run_id = run_id
        self.thread_id = thread_id
        self.query = query
        self.start_time = time.time()
    
    def finish(self, payload: dict, status: str):
        """Record run completion"""
        latency_ms = (time.time() - self.start_time) * 1000
        
        trace_record = {
            "run_id": self.run_id,
            "thread_id": self.thread_id,
            "query": self.query,
            "intent": payload["intent"],
            "status": status,
            "latency_ms": latency_ms,
            "token_usage": payload.get("total_token_usage"),
            "cost_usd": payload.get("total_cost_usd"),
            "used_tools": payload.get("used_tools", []),
            "errors": payload.get("errors", [])
        }
        
        # Write to JSONL
        self.write_jsonl(trace_record)
        
        # Send to Langfuse (if enabled)
        self.send_langfuse(trace_record)
```

**Layer 2: Node-level Tracing**

```python
# app/graph/graph.py
def _instrument_node(node_name: str, fn, observation_type: str = "span"):
    def _wrapped(state: AgentState) -> dict:
        tracer = get_current_tracer()
        if tracer is None:
            return fn(state)
        
        # Record node start
        scope = tracer.start_node(
            node_name=node_name,
            state=state,
            observation_type=observation_type
        )
        
        try:
            update = fn(state)
        except Exception as exc:
            tracer.end_node(scope, error=exc)
            raise
        
        # Record node completion
        tracer.end_node(scope, update=update)
        return update
    
    return _wrapped
```

Tất cả nodes decorated:
```python
builder.add_node(
    "route_intent",
    _instrument_node("route_intent", route_intent, "agent")
)
```

**Trace Output:**

```json
{
  "run_id": "run_abc123",
  "thread_id": "user_456",
  "query": "DAU hôm qua?",
  "intent": "sql",
  "status": "success",
  "latency_ms": 5200,
  "nodes": [
    {
      "name": "detect_context_type",
      "observation_type": "classifier",
      "latency_ms": 150,
      "input_summary": "context_type=default",
      "output_summary": "detected_context=default"
    },
    {
      "name": "route_intent",
      "observation_type": "agent",
      "latency_ms": 2100,
      "output_summary": "intent=sql"
    },
    {
      "name": "get_schema",
      "observation_type": "retriever",
      "latency_ms": 200,
      "output_summary": "tables=[daily_metrics, videos]"
    },
    // ... more nodes
  ],
  "errors": [
    {
      "node": "execute_sql_node",
      "category": "SQL_EXECUTION_ERROR",
      "message": "no such table: videos_v2"
    }
  ]
}
```

**Langfuse Integration:**

Nếu `ENABLE_LANGFUSE=true`:
```bash
export LANGFUSE_PUBLIC_KEY=...
export LANGFUSE_SECRET_KEY=...
```

Traces được gửi tới Langfuse dashboard (cloud).

**Benefits:**
- ✓ Debug: Thấy chính xác request hang ở node nào
- ✓ Monitoring: Track metrics qua time (latency trends, error rates)
- ✓ A/B testing: Langfuse prompt management
- ✓ Replay: JSONL traces có thể replay lại

---

## Phần 8: Final Questions & Wrap-up

### Câu hỏi 8.1: "Điểm yếu của project?"

**Cách trả lời (Honest answer):**

Mỗi project có limitations. Mine:

1. **Prompt version management:**
   - Langfuse integration bị issue với SDK version mismatch
   - Fallback to local prompts, nhưng A/B testing bị limited
   - **Plan:** Upgrade Langfuse SDK khi stable, hoặc tự implement versioning

2. **Qdrant Vector Store complexity:**
   - Conversation memory require separate service (Qdrant)
   - Thêm operational overhead (another service to run)
   - **Plan:** Có thể swap với SQLite vector extension nếu cần simplify

3. **Evaluation coverage:**
   - Groundedness evaluation still fuzzy
   - Khó measure qualitative metrics like "answer usefulness"
   - **Plan:** More sophisticated LLM judges, user feedback loop

4. **Error recovery:**
   - Nếu SQL fail 2 times, system fallback to unknown intent (graceful degradation)
   - Nhưng không có human-in-the-loop để user disambiguate
   - **Plan:** Streaming UI để user can correct LLM mid-execution

5. **Scalability:**
   - Local SQLite không scale cho hundreds of GB data
   - E2B visualization có API rate limits
   - **Plan:** Adapter pattern cho BigQuery/Snowflake, local caching cho E2B

**Honest + Professional:**
Tôi aware của limitations và có plans để address. Tôi trade-off simplicity early (SQLite, local RAG) để ship quick, thay vì over-engineer.

---

### Câu hỏi 8.2: "Nếu xây lại project, bạn làm gì khác?"

**Cách trả lời:**

1. **Design eval framework từ ngày đầu**
   - Thay vì add later
   - Eval-driven development (write test cases trước code)

2. **Plan-and-Execute từ v1**
   - Thay vì v1 linear rồi migrate to v2
   - Parallel architecture là powerful feature, nên có từ đầu

3. **Memory system planned better**
   - Qdrant setup procedure là complex
   - Could use simpler vector store initially (SQLite + extension)

4. **More comprehensive prompt versioning**
   - Could implement custom versioning thay vì rely on Langfuse
   - Better control, less external dependencies

5. **Streaming & live feedback từ đầu**
   - Thay vì monolithic Streamlit
   - Backend + thin client architecture enable better UX

**But also:**
- Tôi learned more từ iterating (v1 → v2, monolithic → microservice) than if planned perfect from start
- Constraints (local-first, simple tools, no auth) forced clean design choices
- Project scale bây giờ perfect cho portfolio (not bloated, not trivial)

---

### Câu hỏi 8.3: "Bạn suggest changes gì cho team muốn adopt?"

**Cách trả lời:**

Nếu team muốn dùng pattern tương tự:

1. **Invest in evaluation first**
   - Define metrics before coding agents
   - Automated gates prevent regressions
   
2. **Use constrained agents**
   - Define tool contracts riêng
   - Don't let LLM freeform
   - Use MCP for standardization

3. **Plan-and-Execute for complex queries**
   - Task decomposition + parallel execution = win
   - Worth investment overhead
   
4. **Separate backend từ UI**
   - Monolithic frameworks cute for demos, tough for production
   - FastAPI + thin client allow better scaling

5. **Memory & continuity**
   - Multi-turn conversations > single-turn
   - User experience dramatically better
   
6. **Observability from day one**
   - Tracing không negotiable
   - Essential for debugging agent behavior

---

## Phần 9: Quick References

### Code Walkthrough Outline

Nếu được hỏi "Walk us through code", làm theo này:

1. **Entry point**: `backend/main.py` hoặc `app/main.py`
   - Show FastAPI app factory
   - Show async wrapper
   
2. **Graph construction**: `app/graph/graph.py`
   - Show build_sql_v2_graph()
   - Walk through nodes + edges
   
3. **Key node**: `route_intent` (shows LLM routing)
   - Show prompt từ `prompts/router.py`
   - Show JSON parsing
   
4. **Another key node**: `analyze_result` (shows Two-Tier data)
   - Show how raw SQL rows → analysis_result
   - Show deterministic processing
   
5. **Tool**: `validate_sql.py`
   - Show regex patterns
   - Show table validation
   
6. **Test**: `tests/test_graph_flow.py`
   - Show how nodes are tested
   - Show monkeypatch for LLM

---

### Quick Talking Points

Nếu bị hỏi nhanh:

- **"Mình làm cái gì?"** → Data analyst agent using LangGraph, SQL safety, Plan-and-Execute architecture
- **"Thách thức gì?"** → Visualization data dependency (nested sequential in parallel)
- **"Tại sao LangGraph?"** → Explicit state, conditional edges, subgraph support
- **"Metrics?"** → Routing accuracy, SQL validity, execution match, groundedness
- **"Eval gates?"** → Block CI if metrics drop (regression prevention)
- **"Memory?"** → Qdrant vector store per thread, continuity detection
- **"Safety?"** → 2-layer SQL validation (regex + table check)
- **"Scaling?"** → Backend + thin client, FastAPI async

---

### Diagram to Draw (if asked)

**Draw at whiteboard:**

```
┌─────────────────────────────────────────────┐
│ User Query (CLI / API / Streamlit)          │
└──────────────────┬──────────────────────────┘
                   │
                   v
        ┌──────────────────────┐
        │ FastAPI Backend      │
        │ (run_query_async)    │
        └──────────┬───────────┘
                   │
                   v
        ┌──────────────────────┐
        │ build_sql_v2_graph() │
        │ (LangGraph)          │
        └──────────┬───────────┘
                   │
        ┌──────────v──────────────────────┐
        │ route_intent (LLM decides)      │
        │ ├─ sql/mixed → task_planner     │
        │ │  └─ Send fan-out (parallel)   │
        │ │     └─ sql_worker × N         │
        │ │        └─ aggregate_results   │
        │ ├─ rag → retrieve_context       │
        │ └─ unknown → synthesize         │
        └──────────┬──────────────────────┘
                   │
              synthesis + memory save
                   │
                   v
            ┌──────────────────┐
            │ JSON Response    │
            │ + JSONL Trace    │
            └──────────────────┘
```

---

## Kết Luận

**Khi kết thúc phỏng vấn:**

"Tóm lại, DA Agent Lab là production-ready agent system demonstrating:
1. Multi-agent orchestration (LangGraph, V1+V2 graphs)
2. SQL safety + Text-to-SQL generation
3. Prompt engineering + few-shot examples
4. Complex architecture (Plan-and-Execute, nested sequential)
5. Evaluation-driven development (gates, metrics)
6. Observability (distributed tracing, Langfuse)
7. Conversation memory & continuity
8. API architecture (FastAPI backend + thin client)

Tôi'm proud với project vì nó demonstrates not just coding, nhưng thinking about scalability, maintainability, observability — những thứ matter trong production AI systems."

---

**Chúc bạn phỏng vấn tốt! 🎉**
