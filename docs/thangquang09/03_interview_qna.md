# Interview Q&A — DA Agent Lab

> Tài liệu này trả lời các câu hỏi phỏng vấn thường gặp về DA Agent Lab.
> Câu trả lời dựa trên **implementation thực tế** trong code, không phải lý thuyết suông.
> Ghi chú "Nhược điểm thật" ở mỗi phần là những thứ tôi sẽ làm khác nếu bắt đầu lại.

---

## 1. Tại sao chọn LangGraph thay vì LangChain Agent?

### Thực tế trong code

LangGraph cho phép tôi định nghĩa graph bằng code rõ ràng:

```python
def build_sql_v3_graph(checkpointer=None):
    builder = StateGraph(AgentState, ...)
    builder.add_edge(START, "process_uploaded_files")
    builder.add_edge("process_uploaded_files", "inject_session_context")
    builder.add_edge("inject_session_context", "task_grounder")
    builder.add_edge("task_grounder", "leader_agent")
    builder.add_edge("leader_agent", "artifact_evaluator")
    builder.add_conditional_edges("artifact_evaluator", _route_after_leader, {...})
    return builder.compile(checkpointer=checkpointer)
```

Mỗi cạnh là **deterministic** — tôi biết chính xác flow sau khi node nào. Không có black box LLM quyết định routing.

### So sánh với LangChain Agent

| Khía cạnh | LangChain Agent | LangGraph StateGraph (DA Agent Lab) |
|-----------|----------------|-------------------------------------|
| Routing | LLM decide khi nào gọi tool | Code deterministic quyết định cạnh nào đi |
| Loop control | LLM decide khi nào dừng | Explicit step counter + artifact_evaluator |
| State access | Qua `agent.state` | TypedDict với annotation |
| Observability | Tuỳ provider | `_instrument_node` wrapper cho mọi node |
| Flexibility | Cao nhưng khó debug | Thấp hơn nhưng predict được |

LangChain Agent dùng ReAct pattern: LLM decide action → execute → observe → repeat. Vấn đề: LLM có thể stuck trong loop, retry không kiểm soát được, observability phải tuỳ chỉnh nhiều.

### Tại sao Supervisor pattern?

Supervisor pattern trong LangGraph = leader đóng vai trò "người điều phối", các worker là deterministic tool. Trong DA Agent Lab:

```python
# leader_agent (lines 1535-1920 trong nodes.py)
# LLM đưa ra quyết định cấp cao: gọi tool nào, với query gì
action = str(parsed.get("action", "")).strip().lower()
if action == "final":
    return final_answer
if action == "tool":
    tool_name = str(parsed.get("tool", "")).strip()
    if tool_name == "ask_sql_analyst":
        tool_result = ask_sql_analyst_tool(state, tool_query)
```

LLM chỉ quyết định **strategy** (gọi tool gì, query gì). Việc execute hoàn toàn deterministic.

**Nhược điểm thật**: Graph có nhiều node hơn LangChain Agent, và mỗi thay đổi flow phải sửa graph builder. LangChain Agent linh hoạt hơn cho prototyping nhanh.

---

## 2. Explain hybrid architecture của bạn

### 2.1 Task Grounder — Tại sao cần?

Task Grounder là một LLM call riêng biệt (dùng `gpt-4o-mini` theo config) để classify query thành structured `TaskProfile`:

```python
# task_grounder.py
def task_grounder(state: AgentState) -> AgentState:
    # ...
    response = client.chat_completion(
        messages=messages,
        model=settings.model_preclassifier,  # gh/gpt-4o-mini
    )
    task_profile: TaskProfile = {
        "task_mode": str(parsed.get("task_mode", "simple")),      # simple | mixed | ambiguous
        "data_source": str(parsed.get("data_source", "database")), # inline_data | uploaded_table | database | knowledge | mixed
        "required_capabilities": parsed.get("required_capabilities", ["sql"]),  # sql | rag | visualization | report
        "followup_mode": str(parsed.get("followup_mode", "fresh_query")),
        "confidence": str(parsed.get("confidence", "medium")),
        "reasoning": str(parsed.get("reasoning", "")),
    }
```

**Tại sao cần Task Grounder thay vì intent classification trong leader?**

1. **Pre-classification trước leader**: Leader không phải guess context từ đầu — đã có `task_profile` sẵn trong state.
2. **Model routing**: Task Grounder dùng model rẻ (`gpt-4o-mini`), không tốn tiền cho việc classification đơn giản.
3. **Separation of concerns**: Classification là metadata, không phải action. Leader chỉ cần đọc profile rồi execute.

**Khác với intent classification**:
- Intent (sql/rag/mixed/unknown) chỉ nói "cần gì"
- TaskProfile nói "cần gì, từ đâu, với confidence nào, ở mode nào"

### 2.2 Artifact Evaluator — Tại sao không để leader quyết?

Artifact Evaluator chạy **sau mỗi leader cycle** để deterministic evaluate artifacts:

```python
def _evaluate_artifacts(state: AgentState) -> AgentState:
    # Map capabilities → artifact types
    CAPABILITY_TO_TYPE = {
        "sql": "sql_result",
        "rag": "rag_context",
        "visualization": "chart",
        "report": "report_draft",
    }

    # Kiểm tra coverage
    collected_types = {a.get("artifact_type") for a in artifacts}
    needed_types = {CAPABILITY_TO_TYPE.get(c) for c in required_caps}

    # Decision logic
    decision: Literal["continue", "finalize", "retry", "wait_for_user"] = "continue"

    if terminal_artifact:
        decision = "finalize"
    elif failed_with_retry:
        decision = "retry"
    elif not missing_types and artifacts:
        decision = "finalize"
    elif task_mode == "ambiguous" or task_confidence == "low":
        decision = "wait_for_user"  # Gọi clarify
```

**Tại sao không để leader tự quyết?**

1. **Loop control an toàn**: Leader loop giới hạn 5 bước — artifact_evaluator là gate cuối cùng.
2. **Deterministic safety**: Không rely vào LLM để biết "đã đủ chưa".
3. **Retry logic tách biệt**: Failed artifact được retry tự động mà không cần leader lặp lại.

**Nhược điểm thật**: Thêm một node nữa trong graph. Mỗi leader call phải qua evaluator trước khi quyết định. Debug loop phức tạp hơn.

### 2.3 Clarify Interrupt — Tại sao cần?

Khi `artifact_evaluator` trả `decision="wait_for_user"`:

```python
# _route_after_leader (graph.py lines 118-138)
def _route_after_leader(state: AgentState) -> str:
    eval_decision = (state.get("artifact_evaluation") or {}).get("decision", "finalize")
    if eval_decision == "wait_for_user":
        return "clarify_question_node"  # interrupt và hỏi user

# clarify_question_node (nodes.py lines 878-915)
def clarify_question_node(state: AgentState) -> AgentState:
    clarification_question = state.get("clarification_question", "")
    prefixed_question = f"[CLARIFY] {clarification_question}"
    return {
        "final_answer": prefixed_question,  # Frontend nhận diện [CLARIFY] prefix
        "confidence": "low",
    }
```

**Tại sao cần interrupt?**

1. **Ambiguous queries**: "Tăng trưởng tốt" — tốt so với cái gì? Cần user specify.
2. **Missing capabilities**: User hỏi về retention nhưng database không có bảng đó.
3. **Avoid hallucination**: Thay vì đoán, hỏi user.

**Frontend handle interrupt** bằng cách detect `[CLARIFY]` prefix trong `final_answer`, hiển thị câu hỏi, và chờ user reply.

### 2.4 Trade-off: Complexity vs Reliability

| Design decision | Complexity | Reliability gain |
|-----------------|------------|------------------|
| Task Grounder riêng | Thêm LLM call, thêm latency | Leader không phải guess |
| Artifact Evaluator riêng | Thêm node, thêm flow | Loop control deterministic |
| Clarify interrupt | Frontend phải handle prefix | Không hallucinate |
| Supervisor pattern | Nhiều code hơn LangChain Agent | Mỗi bước predict được |

**Nhược điểm thật**: Tôi có thể đã over-engineer. Task Grounder + Leader + Artifact Evaluator = 3 LLM calls cho 1 user query. Một single-pass với better prompt có thể đủ cho 80% queries. Cái tôi có là 20% edge cases.

---

## 3. Làm sao đảm bảo SQL safety?

### 3.1 Chỉ SELECT được phép

```python
# validate_sql.py
FORBIDDEN_SQL_PATTERNS = [
    r"\bINSERT\b", r"\bUPDATE\b", r"\bDELETE\b",
    r"\bDROP\b", r"\bALTER\b", r"\bTRUNCATE\b",
    r"\bCREATE\b", r"\bREPLACE\b",
    r"\bATTACH\b", r"\bDETACH\b", r"\bPRAGMA\b",
]
READ_QUERY_PATTERN = re.compile(r"^\s*(SELECT|WITH)\b", flags=re.IGNORECASE | re.DOTALL)

# validate_sql() check
if not READ_QUERY_PATTERN.search(sanitized_sql):
    reasons.append("Only SELECT/CTE read-only queries are allowed.")
for pattern in FORBIDDEN_SQL_PATTERNS:
    if re.search(pattern, sanitized_sql, flags=re.IGNORECASE):
        reasons.append(f"Forbidden SQL keyword detected: {keyword}")
```

### 3.2 Regex block vs AST validation (sqlglot)

Tôi dùng **cả hai**:

```python
# AST extraction bằng sqlglot
def _extract_table_names(sql: str) -> set[str]:
    try:
        parsed = sqlglot.parse_one(sql, read="postgres")
        table_names: set[str] = set()
        for table in parsed.find_all(sqlglot.exp.Table):
            name = table.name
            if name:
                table_names.add(name.lower())
        return table_names
    except sqlglot.errors.ParseError:
        # Fallback to regex
        return _extract_table_names_regex(sql)
```

**Tại sao cả hai?**

Regex đủ cho 90% case nhưng fail với:
- Quoted identifiers: `"MyTable"` vs `MyTable`
- Nested subqueries
- Complex JOINs

AST parsing chính xác hơn nhưng cần `sqlglot` dependency. Fallback regex đề phòng parse error.

### 3.3 CTE Extraction — Tại sao cần?

```python
def _extract_cte_names(sql: str) -> set[str]:
    try:
        parsed = sqlglot.parse_one(sql, read="postgres")
        cte_names: set[str] = set()
        for cte in parsed.find_all(sqlglot.exp.CTE):
            alias = cte.alias
            if alias:
                cte_names.add(alias.lower())
        return cte_names
    except sqlglot.errors.ParseError:
        return _extract_cte_names_regex(sql)
```

**CTE là lừa đảo phổ biến:**

```sql
-- Attacker gửi:
WITH "users" AS (SELECT * FROM sensitive_data)
SELECT * FROM "users"  -- users ở đây là CTE, không phải bảng thật

-- Hoặc:
WITH malicious AS (DROP TABLE users; SELECT 1)
SELECT * FROM malicious
```

Nếu chỉ kiểm tra table names mà không extract CTE names, attacker có thể:

1. Tạo CTE trùng tên với bảng thật
2. CTE chứa DROP TABLE
3. Final SELECT dùng CTE → bypass table check

CTE extraction + table existence check giải quyết cả hai.

### 3.4 Quarantine Schema — xml_database_context

Database schema được inject vào SQL agent prompt dưới dạng XML:

```python
# state.py
xml_database_context: str  # Full <database_context> XML block for SQL agent

# Trong leader_agent prompt
<database_context>
    <tables>
        <table name="users">
            <columns>
                <column name="id" type="INTEGER"/>
                <column name="name" type="TEXT"/>
            </columns>
        </table>
    </tables>
</database_context>
```

**Tại sao XML?**

1. **Structured**: Model parse được dễ dàng hơn natural language.
2. **Isolated**: Chỉ expose tables trong schema, không phải toàn bộ database.
3. **Token-efficient**: XML có thể cắt bớt columns không cần thiết.

**Nhược điểm thật**: XML context có thể rất dài với schema lớn. Tôi chưa implement pagination hay relevance filtering cho schema. Production cần smarter schema selection.

---

## 4. Observability: Làm sao debug khi production fail?

### 4.1 JSONL Trace — run_id, node_name, latency, errors

```python
# tracer.py
class RunTracer:
    def __init__(self, run_id: str, thread_id: str, query: str, trace_path: Path | None = None):
        self.run_id = run_id
        self.trace_path = trace_path or Path(settings.trace_jsonl_path)
        self.node_records: list[NodeTraceRecord] = []

    def end_node(self, scope: NodeScope, update: dict[str, Any] | None = None, error: Exception | None = None):
        record = NodeTraceRecord(
            record_type="node",
            run_id=self.run_id,
            node_name=scope.node_name,
            attempt=scope.attempt,
            latency_ms=latency_ms,
            error_category=error_category,  # SQL_VALIDATION_ERROR, ROUTING_ERROR, etc.
            error_message=error_message,
        )
        self._append_jsonl(record.to_dict())
```

Mỗi node ghi một JSON line vào file:

```json
{"record_type":"node","run_id":"abc123","node_name":"leader_agent","attempt":1,"latency_ms":2340.5,"status":"ok","error_category":null}
{"record_type":"run","run_id":"abc123","thread_id":"user-42","status":"success","intent":"sql","total_steps":3,"error_categories":[]}
```

### 4.2 Langfuse Integration — prompt versioning, trace replay

```python
# tracer.py
class LangfuseAdapter:
    def start_run(self, run_id: str, query: str, thread_id: str) -> None:
        self.root_observation = self.client.start_observation(
            name="da-agent-run",
            as_type="agent",
            input={"query": query, "run_id": run_id, "thread_id": thread_id},
            metadata={"project": {...}},
        )

    def end_node(self, node_obs, update, error_message) -> None:
        node_obs.update(output={"update": _output_summary(update)})
        node_obs.end()
```

Langfuse cho phép:
- **Replay trace**: Click vào run, xem từng node call với input/output
- **Prompt versioning**: Mỗi LLM call ghi lại model, prompt version, token usage
- **Score evaluation**: Gắn score cho từng run để track quality

### 4.3 @trace_node Decorator — Cách hoạt động

```python
# graph.py
def _instrument_node(node_name: str, fn, observation_type: str = "span"):
    def _wrapped(state: AgentState) -> AgentState:
        tracer = get_current_tracer()  # ContextVar
        if tracer is None:
            return fn(state)
        scope = tracer.start_node(node_name=node_name, state=state, observation_type=observation_type)
        try:
            update = fn(state)
        except Exception as exc:
            tracer.end_node(scope, error=exc)
            raise
        tracer.end_node(scope, update=update)
        return update
    return _wrapped
```

**Cách hoạt động:**

1. `ContextVar` lưu current tracer — để bất kỳ node nào trong thread đều access được.
2. `_instrument_node` wrap mọi node, gọi `tracer.start_node()` trước và `tracer.end_node()` sau.
3. Decorator không thay đổi logic node — chỉ thêm observability.

### 4.4 Debug Mode

Debug mode enable qua config:

```python
# app/config.py
debug_mode: bool = os.getenv("DEBUG_MODE", "false").lower() == "true"
```

Debug mode thường enable:
- Verbose logging
- Full state dump thay vì truncated
- Không flush Langfuse (giữ traces trong memory)

**Nhược điểm thật**: Tôi chưa implement structured error categories đầy đủ. `error_categories` trong trace chỉ là string matching, không phải typed enum. Refactor thành proper exception hierarchy sẽ tốt hơn.

---

## 5. Token Optimization

### 5.1 Task Grounder dùng model rẻ (mini) — Tại sao đúng?

```python
# task_grounder.py
response = client.chat_completion(
    messages=messages,
    model=settings.model_preclassifier,  # gh/gpt-4o-mini
    temperature=0.0,
    stream=False,
)
```

**Task Grounder là classification, không phải reasoning:**

- Classification: "query này cần SQL, confidence cao" → gpt-4o-mini đủ
- Reasoning: "viết SQL phức tạp với window function" → cần gpt-4o

Cost comparison:
- `gpt-4o-mini`: ~$0.15/1M tokens (input)
- `gpt-4o`: ~$2.5/1M tokens (input)
- **16x cost difference**

Với 1000 queries/day:
- Task Grounder mini: ~$0.05/day
- Task Grounder gpt-4o: ~$0.80/day

Trong architecture này, Task Grounder chạy **1 lần/query**. Leader agent có thể chạy 1-5 lần. Mini cho classification là **đúng đắn về cost**.

### 5.2 Scratchpad Growth — Khi nào thành vấn đề?

```python
# leader_agent loop (nodes.py lines 1603-1886)
scratchpad_entries: list[str] = []

for step in range(1, 6):  # Max 5 iterations
    messages = prompt_manager.leader_agent_messages(
        scratchpad="\n\n".join(scratchpad_entries),  # Accumulated
        ...
    )
    # ... tool call ...
    scratchpad_entries.append(
        f"[Step {step}] tool={tool_name}\n{_summarize_tool_result(tool_name, tool_result)}"
    )
```

**Vấn đề:**

1. **Scratchpad tích lũy**: Mỗi iteration thêm 1 entry. 5 iterations = 5 tool results.
2. **Prompt bự**: Tool results có thể chứa SQL, RAG context, data samples.
3. **Context overflow**: Với complex query, scratchpad có thể chiếm 50%+ context window.

**Mitigation đang có:**

```python
def _summarize_tool_result(tool_name: str, tool_result: dict[str, Any]) -> str:
    # Chỉ lấy summary, không lấy full result
    return f"status=ok, row_count={tool_result.get('sql_result', {}).get('row_count', 0)}"
```

**Nhược điểm thật**: Mitigation hiện tại yếu. Nên có hard limit trên scratchpad entries (ví dụ: chỉ giữ 3 entries gần nhất), hoặc dùng `compact_and_save_memory` pattern để truncate.

### 5.3 Prompt Caching Opportunity

```python
# app/config.py
model_preclassifier = os.getenv("MODEL_PRECLASSIFIER", "gh/gpt-4o-mini")
model_leader = os.getenv("MODEL_LEADER", default_model)
```

`litellm` hỗ trợ prompt caching qua provider:

```python
# Nếu provider support, litellm tự động cache
response = client.chat_completion(
    messages=messages,
    model=settings.model_preclassifier,
    # litellm sẽ detect identical system prompt
    # và dùng cached version nếu available
)
```

**Opportunity:**

- System prompts cho Task Grounder và SQL Agent có thể cache vì không đổi giữa các calls.
- Tiết kiệm 30-50% tokens cho repeated queries.

**Nhược điểm thật**: Prompt caching hiện tại chỉ passive qua litellm. Không có explicit cache key hay invalidate strategy. Với frequent repeated queries, nên implement smart cache.

---

## 6. Edge Cases khó

### 6.1 Ambiguous Query — Hệ thống phản ứng thế nào?

**Flow:**

```python
# task_grounder
task_profile = {
    "task_mode": "ambiguous",  # Hoặc "confidence": "low"
    ...
}

# _evaluate_artifacts
elif task_mode == "ambiguous" or task_confidence == "low":
    clarification_question = _generate_clarification_question(
        user_query=user_query,
        task_profile=task_profile,
        collected=collected_types,
        missing=missing_types,
    )
    decision = "wait_for_user"

# Frontend nhận
final_answer = "[CLARIFY] Câu hỏi của bạn hơi mơ hồ..."
```

**Ví dụ:**

User: "Tăng trưởng tốt"

1. Task Grounder → `task_mode="ambiguous"`, `confidence="low"`
2. Leader cố gắng execute nhưng artifacts không cover được
3. Artifact Evaluator → `decision="wait_for_user"`
4. User nhận: `"[CLARIFY] Tăng trưởng tốt so với tháng trước? Quý trước? Hay kỳ vọng?"`

**Nhược điểm thật**: Ambiguous detection phụ thuộc vào Task Grounder prompt. Nếu Grounder bị confused, ambiguous query có thể pass qua và lead đến wrong answer. Cần eval coverage tốt.

### 6.2 Visualization E2B Timeout — Trải nghiệm user ra sao?

```python
# standalone_visualization.py exception handler
except Exception as exc:
    error_msg = str(exc)

    if "sandbox" in error_msg.lower() and (
        "timeout" in error_msg.lower() or "not found" in error_msg.lower()
    ):
        user_error = (
            "Visualization sandbox timed out while starting. "
            "This may be due to high demand. Please try again later."
        )
    elif "api key" in error_msg.lower():
        user_error = (
            "Visualization service API key is invalid. Please contact support."
        )
    else:
        user_error = f"Visualization failed: {error_msg}"

    return {
        "visualization": {"success": False, "error": user_error},
        "status": "failed",
        "artifact_recommended_action": "clarify",
    }
```

**User experience:**

- Nếu E2B timeout: User nhận message rõ ràng, có thể retry.
- Visualization không block toàn bộ query — nếu user chỉ hỏi "biểu đồ", có thể fallback answer.
- E2B là optional enhancement, không phải core functionality.

**Nhược điểm thật**: Không có retry với exponential backoff. Không có circuit breaker. Nếu E2B down, user phải retry thủ công.

### 6.3 Inline Data vs DB Data — Làm sao phân biệt?

```python
# standalone_visualization.py — NEVER touches database
def inline_data_worker(task_state: TaskState) -> dict[str, Any]:
    # raw_data từ user input, KHÔNG từ database
    raw_data = task_state.get("raw_data", [])

# Task Grounder classify data source
task_profile = {
    "data_source": "inline_data",  # vs "database" vs "uploaded_table"
    ...
}
```

**Distinction trong state:**

| Source | Artifact | Evidence |
|--------|----------|----------|
| Database | `sql_result` artifact | `validated_sql`, `sql_row_count` |
| Inline data | `chart` artifact với `source: "inline_data"` | `raw_data` count |
| Uploaded table | `sql_result` với `uploaded_file_data` | `registered_tables` |

**Manifesto đằng sau:**

- **Inline data**: User cung cấp raw numbers → không cần SQL → visualization worker bypass database hoàn toàn.
- **Database**: SQL query → validate → execute → analyze.

**Nhược điểm thật**: Không có explicit flag để distinguish trong final answer. User có thể không biết câu trả lời đến từ DB hay từ data họ upload.

### 6.4 Empty SQL Result — Trả lời user thế nào?

```python
# tracer.py
row_count = payload.get("rows")
if isinstance(row_count, int) and row_count == 0 and payload.get("intent") in {"sql", "mixed"}:
    error_categories.append("EMPTY_RESULT")
```

**Flow:**

1. SQL execute thành công nhưng không có rows.
2. `sql_row_count = 0` được track.
3. Leader agent synthesize answer:
   - Không nói "0 results" rỗng
   - Thay vào đó: "Không tìm thấy dữ liệu phù hợp với điều kiện..."
4. `error_categories` ghi `EMPTY_RESULT` để track pattern.

**Nhược điểm thật**: Empty result handling phụ thuộc vào leader prompt. Không có explicit template. Prompt có thể thay đổi quality. Cần structured evaluation cho case này.

---

## 7. Scaling Challenges

### 7.1 Concurrent Users — checkpointer + thread_id

```python
# graph.py
def build_sql_v3_graph(checkpointer=None):
    # checkpointer được inject từ caller
    return builder.compile(checkpointer=checkpointer or InMemorySaver())

# app/main.py hoặc streamlit
from langgraph.checkpoint.postgres import PostgresSaver
checkpointer = PostgresSaver.from_conn_string(DB_URL)
graph = build_sql_v3_graph(checkpointer=checkpointer)

# Mỗi user có thread_id riêng
config = {"configurable": {"thread_id": "user-42-session-1"}}
result = graph.invoke(input_state, config=config)
```

**Những gì checkpointer làm:**

1. **Serialize state** sau mỗi node
2. **Resume** từ checkpoint thay vì restart
3. **Isolate** users: thread A không thấy thread B state

**Những gì tôi implement:**

```python
# inject_session_context (nodes.py)
thread_id = state.get("thread_id")
if thread_id:
    recent_turns = conv_store.get_recent_turns(thread_id, limit=MAX_TURNS_IN_CONTEXT)
    # Inject conversation history vào session_context
```

### 7.2 Database Bottleneck — SQLite Limitations

```python
# validate_sql.py
with sqlite3.connect(db_path) as conn:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ...").fetchall()
    table_names = {row[0].lower() for row in rows}
```

**SQLite limitations cho production:**

1. **Write contention**: WAL mode giúp read concurrency, nhưng write serialize hoàn toàn.
2. **Connection per query**: Mỗi `sqlite3.connect()` tạo new connection.
3. **No parallel query execution**: SQLite không có query planner đa luồng.

**Mitigation đang có:**

- `result_ref` pattern: Chỉ lưu metadata, không lưu full rows trong state.
- `compact_and_save_memory`: Giảm conversation history size.

**Nhược điểm thật**: SQLite chỉ phù hợp cho development/demo. Production cần PostgreSQL hoặc ClickHouse. Tôi chưa implement connection pooling hay query result pagination.

### 7.3 Long Context — Mitigation Strategies

```python
# compact_and_save_memory (nodes.py)
def _compact_conversation(conv_store, thread_id):
    MAX_TURNS_IN_CONTEXT = 10
    MAX_TURNS_IN_SUMMARY = 5

    # 1. Truncate recent turns
    recent = conv_store.get_recent_turns(thread_id, limit=50)
    if len(recent) > MAX_TURNS_IN_CONTEXT:
        # 2. Generate summary cho old turns
        old_summary = _summarize_turns(old_turns)
        # 3. Replace old turns bằng summary
        conv_store.replace_with_summary(thread_id, old_summary)

def _summarize_turns(turns: list[dict]) -> str:
    # Dùng LLM để summarize old conversation
    # Returns: "User hỏi về DAU. Agent trả lời với data từ Jan 2025..."
```

**Mitigation strategies đang có:**

1. **Turn limit**: Chỉ giữ 10 turns gần nhất trong context.
2. **Summarization**: Old turns được summarize thành 1-2 sentences.
3. **Schema truncation**: XML database context có thể cắt bớt columns.
4. **Scratchpad summarization**: Tool results được summarize thay vì full dump.

**Nhược điểm thật**: Summarization là best-effort. Summary có thể miss important details. Không có explicit budget tracking trong prompt.

---

## Tổng kết — Những thứ tôi sẽ làm khác

| Quyết định | Bây giờ | Nếu làm lại |
|-----------|---------|-------------|
| Task Grounder riêng | Mini model, pre-classification | Có thể gộp vào leader với better prompt |
| Artifact Evaluator riêng | Deterministic coverage check | Giữ — quan trọng cho safety |
| SQLite | Dev database | PostgreSQL từ đầu |
| E2B Visualization | Direct integration | Add circuit breaker, retry |
| Prompt caching | Passive via litellm | Explicit cache management |
| Error categories | String matching | Typed exception hierarchy |
| Clarify interrupt | Frontend handle prefix | Structured interrupt protocol |

**Core strength của hệ thống này:**

- SQL safety là **production-ready**, không phải demo
- Observability cho phép debug production issues trong minutes
- Graph structure predict được — không có black box

**Điều cần cải thiện nhất:**

1. Evaluation framework cho routing + answer quality
2. Proper async support cho concurrent users
3. Structured error handling thay vì string matching
