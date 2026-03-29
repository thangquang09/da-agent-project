# Ghi chú riêng cho Thắng - DA Agent
Cập nhật: 2026-03-29

## 1) Trạng thái hiện tại
- **Week 1 coi như hoàn thành về mặt kỹ thuật cốt lõi** (core flow đã chạy được).
- Đã có:
  - LangGraph orchestration (không phải code thuần)
  - SQL tools + safety validation
  - CLI chạy end-to-end
  - Streamlit UI cơ bản
  - Router đã chuyển sang **LLM-first** + fallback an toàn
  - Prompt tách riêng để quản lý

## 2) Bạn hỏi đúng 2 điểm quan trọng
### A. "LLM code thuần, không có LangGraph?"
- Hiện tại **có LangGraph thật** ở `app/graph/graph.py`.
- Node/tool vẫn là Python function (đây là chuẩn của LangGraph).

### B. "route_intent fix cứng"
- Đã đổi sang **agent (LLM) quyết định intent** (`sql/rag/mixed`) bằng output JSON có kiểm soát.
- Nếu LLM lỗi/JSON sai, hệ thống fallback heuristic để không vỡ luồng.

## 3) Quy ước kỹ thuật đang áp dụng
- Env loader: `pydotenv`
- Logger chuẩn toàn project: `loguru`
- API rule bắt buộc: luôn `stream=false`

## 4) Test để ổn định (mới thêm)
Mục tiêu: tránh việc phải chạy đi chạy lại nhiều lệnh thủ công.

### Đã thiết lập
- `pytest` + `pytest-cov`
- `tests/conftest.py` tự seed DB trước test
- Test SQL tools
- Test graph flow (SQL path, RAG placeholder, fail-fast validation)
- Config pytest trong `pyproject.toml`

### Chạy test 1 lệnh
```powershell
uv run pytest
```

### Nếu muốn xem coverage
```powershell
uv run pytest --cov=app --cov-report=term-missing
```

## 5) Lệnh chạy nhanh hàng ngày
### Seed DB
```powershell
uv run python data/seeds/create_seed_db.py
```

### Smoke test CLI
```powershell
uv run python -m app.main "DAU 7 ngày gần đây như thế nào?"
```

### Chạy UI
```powershell
uv run streamlit run streamlit_app.py
```

## 6) Các file chính nên đọc
- `implementation_todo.md`
- `app/graph/graph.py`
- `app/graph/nodes.py`
- `app/prompts/router.py`
- `app/prompts/sql.py`
- `app/tools/`
- `tests/`

## 7) Bước kế tiếp mình đang làm
- Hoàn thiện Week 2:
  - nhánh `rag`
  - nhánh `mixed`
  - retriever + merge logic
  - observability và eval sâu hơn
