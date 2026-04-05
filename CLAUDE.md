# CLAUDE.md

## Documentation rules

> **QUAN TRỌNG — Đọc trước khi bắt đầu làm việc.**

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

## Skills

- `context7` — Look up latest API documentation of libraries.
- `langgraph` — `.codex/skills/mastering-langgraph/SKILL.md`
- `nlm` (NotebookLM) — `.agents/skills/nlm-skill/SKILL.md` — Notebook `LLM - KD - AI AGENT` cho kiến thức về LLMs, Agents, MCP.
- `langfuse` — `.agents/skills/langfuse/SKILL.md` — Agent tracing with Langfuse.

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

## Routing behavior

| Query type | Intent | Example |
|-----------|--------|---------|
| Hỏi giá trị, ranking, trend | `sql` | "DAU hôm qua là bao nhiêu?" |
| Hỏi định nghĩa, business rule | `rag` | "Retention D1 là gì?" |
| Cần cả data lẫn context | `mixed` | "Retention giảm từ ngày nào và metric này tính ra sao?" |

Route bằng structured output (enum), không phải free-form text.

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

## Non-goals (early versions)

- Polished enterprise UI
- Multi-tenant auth / production infra / large-scale deployment
- Premature multi-agent complexity
- Over-engineered microservices

---

## Code conventions

Tóm tắt quan trọng nhất:

- **Logging**: `loguru` only, structured placeholders, never log secrets.
- **Imports**: `from __future__ import annotations` first, grouped (stdlib → third-party → local).
- **Types**: modern `|` union syntax, `TypedDict` for state, `Literal` for enums.
- **Naming**: files `snake_case`, classes `PascalCase`, constants `SCREAMING_SNAKE_CASE`.
- **Testing**: `pytest` + `monkeypatch` + `conftest.py` fixtures.

> **Chi tiết đầy đủ**: `docs/CODE_STYLE.md`

---

## Project purpose & interview value

Dự án này là **applied AI portfolio project** cho vị trí AI/Agent Engineer. Mapping với:
- AI application prototyping, tool-calling agents, RAG pipelines
- Prompt design, MCP-style tool surfaces
- SQL/data infrastructure, evaluation, observability

Khi đánh giá một change, tự hỏi:

> *"Change này có giúp system dễ explain, debug, evaluate, và defend trong interview không?"*

Có → good change. Không → probably a distraction.

---

## Key documentation map

| File | Nội dung |
|------|----------|
| `CLAUDE.md` (file này) | Tổng quan, quick ref, principles — **source of truth cho agent** |
| `docs/thangquang09/system_design.md` | Kiến trúc chi tiết, state model, nodes, tools, eval, data |
| `docs/CODE_STYLE.md` | Code conventions, naming, patterns |
| `docs/thangquang09/overview.md` | Project overview |
| `docs/thangquang09/implementation_todo.md` | Implementation tracking |
| `docs/research/` | Research notes, datasets, RAG docs, eval pipeline |
| `app/prompts/CLAUDE.md` | Prompt inventory — all LLM prompts are defined in `app/prompts/` |

---

## Available tools

- GitHub MCP — tìm kiếm public code tham khảo.
- NotebookLM MCP — [Notebook link](https://notebooklm.google.com/notebook/5220d387-0fa4-4250-8206-435e684c1c0e) — kiến thức thực tế lẫn lý thuyết về AI Engineer.

---

<!-- ClaudeVibeCodeKit -->
## ClaudeVibeCodeKit

### Planning
When planning complex tasks:
1. Read `.claude/docs/plan-execution-guide.md` for format guide
2. Use planning-agent for parallel execution optimization
3. Output plan according to `.claude/schemas/plan-schema.json`

### Available Commands
- `/research <topic>` - Deep web research
- `/meeting-notes <name>` - Live meeting notes
- `/changelog` - Generate changelog
- `/onboard` - Developer onboarding
- `/handoff` - Create handoff document for conversation transition
- `/continue` - Resume work from a handoff document
- `/watzup` - Check current project status
- `/social-media-post` - Social content workflow
<!-- /ClaudeVibeCodeKit -->
