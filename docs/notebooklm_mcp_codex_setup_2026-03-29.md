# NotebookLM MCP CLI - Codex Setup Report (2026-03-29)

## Mục tiêu
Cài đặt và xác nhận `notebooklm-mcp-cli` cho Codex trong môi trường local.

## Trạng thái
- Package: `notebooklm-mcp-cli` `v0.5.11`
- MCP cho Codex: `configured` (`nlm setup add codex` thành công)
- Auth profile: `default` (đã re-auth thành công)
- Skill files: đã cài project-level vào `.agents/skills/nlm-skill`

## Các lệnh đã chạy (chính)
```powershell
uv tool install notebooklm-mcp-cli
$env:PYTHONIOENCODING='utf-8'; nlm setup add codex
$env:PYTHONIOENCODING='utf-8'; nlm setup list
codex mcp list
$env:PYTHONIOENCODING='utf-8'; nlm login --clear
$env:PYTHONIOENCODING='utf-8'; nlm login --check
$env:PYTHONIOENCODING='utf-8'; nlm notebook list
$env:PYTHONIOENCODING='utf-8'; nlm notebook query 5220d387-0fa4-4250-8206-435e684c1c0e "Notebook này tập trung vào chủ đề gì? Trả lời 3 ý ngắn." --json
$env:PYTHONIOENCODING='utf-8'; nlm skill install agents --level project
```

## Kết quả kiểm thử
### 1) Binary/CLI health
- `nlm --help`: OK
- `notebooklm-mcp --help`: OK
- `nlm --version`: OK (`0.5.11`, latest)

### 2) Codex integration
- `nlm setup add codex`: OK
- `codex mcp list`: có `notebooklm-mcp` trạng thái `enabled`

### 3) Authentication
- Ban đầu: `nlm login --check` báo expired
- Sau khi chạy `nlm login --clear`: xác thực lại thành công
- `nlm login --check`: valid, thấy account và notebook count

### 4) End-to-end NotebookLM query
- `nlm notebook list`: trả về danh sách notebook thành công
- `nlm notebook query ... --json`: trả về answer + citations + references thành công

### 5) MCP tools (runtime)
- `notebook_list`: OK
- `notebook_query`: OK

## Lưu ý vận hành (Windows)
- Một số lệnh `nlm setup/*` có thể lỗi `UnicodeEncodeError` với console CP1252.
- Workaround ổn định:
  - Set `PYTHONIOENCODING=utf-8` trước khi chạy lệnh `nlm`.
- Đã gặp lỗi CDP process-map trên `nlm login` thường; `nlm login --clear` xử lý được trong lần này.

## Artifacts tạo thêm
- `.agents/skills/nlm-skill/` (skill project-level)
- Tài liệu này: `docs/notebooklm_mcp_codex_setup_2026-03-29.md`
