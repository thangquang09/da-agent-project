# Environment Variables

This document lists the environment variables used in the project, extracted from `.env` templates.

<!-- AUTO-GENERATED: ENV -->
| Variable | Required | Description | Example | Default |
|----------|----------|-------------|---------|--------|
| `DATABASE_URL` | Yes | PostgreSQL connection string | `postgresql://postgres:postgres@localhost:5432/postgres` | — |
| `LLM_API_URL` | Yes | Base URL for the LLM API | `https://.../v1/chat/completions` | — |
| `LLM_API_KEY` | Yes | API Key for the LLM | `sk-...` | — |
| `E2B_API_KEY` | No | E2B sandbox API key for code execution/visualization | `e2b-...` | — |
| `ENABLE_LANGFUSE` | No | Enable Langfuse observability | `true`/`false` | `false` |
| `LANGFUSE_PUBLIC_KEY` | No | Public key for Langfuse observability | `pk-lf-...` | — |
| `LANGFUSE_SECRET_KEY` | No | Secret key for Langfuse observability | `sk-lf-...` | — |
| `LANGFUSE_HOST` | No | Base URL for Langfuse | `https://cloud.langfuse.com` | — |
| `ENABLE_MCP_TOOL_CLIENT` | No | Enable MCP tool client | `true`/`false` | `false` |
| `BACKEND_URL` | No | Backend URL (for Streamlit) | `http://localhost:8001` | `http://localhost:8001` |
| `BACKEND_PORT` | No | Backend port (Docker override) | `8001` | `8001` |
| `FRONTEND_PORT` | No | Frontend port (Docker override) | `8501` | `8501` |
| `MCP_PORT` | No | MCP server port (Docker override) | `8000` | `8000` |
| `TRACE_JSONL_PATH` | No | Path to trace JSONL output | `evals/reports/traces.jsonl` | `evals/reports/traces.jsonl` |
<!-- /AUTO-GENERATED: ENV -->
