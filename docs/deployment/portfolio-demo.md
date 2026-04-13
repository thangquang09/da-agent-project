# Portfolio demo deployment blueprint

Mục tiêu: deploy bản demo **ổn định, rẻ, dễ giải thích** với stack:

- **Frontend:** Vercel Hobby
- **Backend:** Modal
- **Database:** Neon Postgres
- **CI/CD:** GitHub Actions

## 1) Scope khuyên dùng

Ưu tiên bản demo theo hướng:

- `APP_MODE=demo`
- **Tắt** Qdrant / embeddings / startup embedding prewarm
- **Tắt** visualization runtime nếu không phải wow-feature chính
- **Tắt** Langfuse nếu không định show observability
- Chỉ giữ 2–3 flow demo đẹp nhất

## 2) Biến môi trường tối thiểu

Dùng `.env.example.demo` làm mẫu. Tối thiểu cần:

- `DATABASE_URL`
- `LLM_API_URL`
- `LLM_API_KEY`
- `NEXT_PUBLIC_API_URL`
- `BACKEND_CORS_ORIGINS`

## 3) Neon

Khuyên dùng **pooled connection string** của Neon cho `DATABASE_URL`.

Checklist:

1. Tạo project + database trên Neon
2. Lấy pooled connection string
3. Gán vào:
   - local `.env`
   - GitHub Actions secrets nếu cần
   - Modal secret `da-agent-demo-env`

## 4) Modal

Repo đã có entrypoint ở `deploy/modal_app.py`.

Triển khai:

```bash
uv pip install modal
modal token new
modal secret create da-agent-demo-env \
  DATABASE_URL=... \
  LLM_API_URL=... \
  LLM_API_KEY=... \
  APP_MODE=demo \
  ENABLE_QDRANT=false \
  ENABLE_VISUALIZATION=false \
  ENABLE_LANGFUSE=false \
  ENABLE_STARTUP_EMBEDDING_PREWARM=false \
  ARTIFACT_MODE=local \
  TYPE_OF_SANDBOX=none

modal deploy deploy/modal_app.py
```

Sau deploy, lấy URL của web endpoint và dùng nó cho `NEXT_PUBLIC_API_URL` trên Vercel.

## 5) Vercel

Frontend dùng `frontend/`.

Thiết lập:

- Framework: Next.js
- Root directory: `frontend`
- Env var:
  - `NEXT_PUBLIC_API_URL=https://<modal-endpoint>`

Khuyên dùng luôn `vercel.app` cho bản đầu.

## 6) Health / readiness

Backend đã có:

- `GET /health`: liveness
- `GET /ready`: readiness chi tiết hơn

`/ready` kiểm:

- database
- artifact root
- visualization flag
- qdrant flag
- langfuse flag

## 7) GitHub Actions

Repo đã có workflow `.github/workflows/ci.yml`.

Hiện workflow chạy:

- backend tests
- backend health + readiness smoke test
- frontend lint
- frontend typecheck
- frontend build

## 8) Demo runbook

Trước lúc demo:

1. Mở frontend production URL
2. Gọi trước một request đơn giản để warm backend
3. Kiểm tra `/ready`
4. Chuẩn bị sẵn:
   - screenshots
   - sample artifact
   - video fallback

## 9) Những gì chưa làm trong blueprint này

Đã **tạm bỏ qua artifact cloud storage** theo quyết định hiện tại.

Nếu sau này cần artifact tạo live và tồn tại bền vững sau redeploy/restart:

- thêm object storage
- đổi `ARTIFACT_MODE`
- bỏ local filesystem khỏi flow chính
