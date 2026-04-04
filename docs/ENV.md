# Environment Variables

This document lists the environment variables used in the project, extracted from `.env` templates.

<!-- AUTO-GENERATED: ENV -->
| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `DATABASE_URL` | Yes | PostgreSQL connection string | `postgresql://postgres:postgres@localhost:5432/postgres` |
| `LLM_API_URL` | Yes | Base URL for the LLM API | `https://.../v1/chat/completions` |
| `LLM_API_KEY` | Yes | API Key for the LLM | `sk-...` |
| `LANGFUSE_SECRET_KEY` | No | Secret key for Langfuse observability | `sk-lf-...` |
| `LANGFUSE_PUBLIC_KEY` | No | Public key for Langfuse observability | `pk-lf-...` |
| `LANGFUSE_BASE_URL` | No | Base URL for Langfuse | `https://cloud.langfuse.com` |
| `LANGFUSE_PROJECT_NAME` | No | Langfuse project name | `da-agent-project` |
| `LANGFUSE_PROJECT_ID` | No | Langfuse project ID | `cmncpq4xj0010ad07yughrjzi` |
| `LANGFUSE_ORG_NAME` | No | Langfuse organization name | `Kyanon_AppliedTrainee` |
| `LANGFUSE_ORG_ID` | No | Langfuse organization ID | `EU` |
| `ENABLE_LLM_SQL_GENERATION` | No | Enable LLM SQL generation (default: true) | `true` |
<!-- /AUTO-GENERATED: ENV -->
