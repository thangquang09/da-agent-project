# AGENTS.md / CLAUDE.md

> **QUAN TRỌNG — Chỉ đọc 1 trong 2 file này!**
> - Nếu bạn là **coding agent (Claude Code)**: đọc `CLAUDE.md`
> - Nếu bạn là **planning/execution agent (OpenCode/GitHub Agent)**: đọc `AGENTS.md`
> - **KHÔNG đọc cả 2** để tránh context overload.

---

## Documentation rules

> **QUAN TRỌNG — Đọc trước khi bắt đầu làm việc.**

- Sau khi cập nhật nội dung trong `CLAUDE.md` hoặc `AGENTS.md`, chạy script sync:
  ```bash
  python scripts/sync_claude_agents.py
  ```
- Luôn cập nhật documentation sau khi implement xong một feature.
- **KHÔNG** nhét nội dung chi tiết vào file này. File này chỉ chứa tóm tắt + link.
- Khi cần ghi lại kiến trúc mới, design decision, hoặc research → tạo/cập nhật file riêng trong `docs/` rồi link từ đây.
- Khi cần thêm convention mới → cập nhật `docs/CODE_STYLE.md`, không thêm vào đây.
- Giữ file này **dưới 300 dòng**. Nếu vượt, tách nội dung ra file riêng.

---

## Project

**DA Agent Lab** — A LangGraph-based Data Analyst Agent.

Trả lời business/data questions qua SQL tools, RAG retrieval, deterministic analysis, và full observability.

- **Runtime**: `uv` virtualenv (`.venv`)
- **Database**: SQLite local warehouse
- **LLM orchestration**: LangGraph
- **Observability**: JSONL traces + Langfuse

---

## Quick reference — Dev commands

```bash
# Run
streamlit run streamlit_app.py    # Streamlit UI
python -m app.main                # CLI
python -m mcp_server.server       # MCP server

# Test
pytest                                          # All tests
pytest tests/test_sql_tools.py -v               # Single file
pytest -k "validate_sql"                        # Pattern match
pytest --cov=app --cov-report=term-missing      # Coverage

# Data
python data/seeds/create_seed_db.py             # Seed database

# Eval
python evals/runner.py                          # Run eval suite
```

---

## Architecture overview

```text
User (CLI / Streamlit)
        |
        v
  LangGraph StateGraph
        |
        +-- detect_context_type
        +-- route_intent  →  sql | rag | mixed | unknown
        |       |
        |       +→ sql  → get_schema → generate_sql → validate → execute → analyze
        |       +→ rag  → retrieve_context
        |       +→ unknown → synthesize (LLM fallback)
        |
        v
  synthesize_answer
        |
        v
  Trace (JSONL + Langfuse)
```

> **Chi tiết đầy đủ**: `docs/thangquang09/system_design.md`
> Bao gồm: state model, node design, tool specs, data strategy, failure taxonomy, eval framework, MCP guidance.

---

## Core principles

1. **Constrained agent** — LLM decides, tools execute, deterministic code analyzes. Không cho LLM tự do hành động ngoài tool surfaces đã định nghĩa.

2. **Observability-first** — Mỗi run phải capture: run_id, routing decision, used tools, generated SQL, latency, errors. Traces phải replayable.

3. **SQL safety** — Chỉ cho phép `SELECT` / CTE. Block tuyệt đối: `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `CREATE`, `REPLACE`. Validate trước khi execute.

4. **Evaluation-driven** — Đo routing accuracy, SQL validity, tool-call correctness, answer quality. Chạy regression sau mỗi prompt/tool change.

5. **Grounded answers** — Không bịa số liệu. Phân biệt rõ data từ DB vs context từ RAG vs phân tích suy luận. Thừa nhận uncertainty khi data thiếu.

---

## Implementation priorities

Khi contribute, ưu tiên theo thứ tự:

1. Correctness
2. Observability
3. Evaluation
4. Clarity of architecture
5. Feature expansion
6. UI polish

> Chọn implementation nhỏ nhưng đo lường được, hơn là implementation lớn nhưng mơ hồ.

---

## Key documentation map

| File | Nội dung |
|------|----------|
| `AGENTS.md` (file này) | Tổng quan, quick ref, principles — **source of truth cho planning/execution agent** |
| `docs/thangquang09/overview.md` | Project overview |
| `docs/thangquang09/implementation_todo.md` | Implementation tracking |
| `docs/CODE_STYLE.md` | Code conventions, naming, patterns |
| `app/prompts/AGENTS.md` | Prompt inventory |

---

## Available tools

- GitHub MCP — tìm kiếm public code tham khảo.
- NotebookLM MCP — [Notebook link](https://notebooklm.google.com/notebook/5220d387-0fa4-4250-8206-435e684c1c0e) — kiến thức thực tế lẫn lý thuyết về AI Engineer.
- GitNexusMCP - Codebase intelligence zero-server: phù hợp cho phân tích codebase, luôn sử dụng nó trước khi thực hiện glob/read files.
