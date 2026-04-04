# Runbook

This document contains operational procedures and troubleshooting guides.

## Deployment Procedures

The project uses Docker Compose with PostgreSQL as the primary database.

1. Start PostgreSQL:
   ```bash
   docker compose up -d postgres
   ```
2. Seed the database (first time):
   ```bash
   PYTHONPATH=. python data/seeds/create_seed_db.py
   ```
3. Build and start all services:
   ```bash
   docker compose up --build
   ```
4. Verify logs:
   ```bash
   docker compose logs -f
   ```

## Local Operations

- **Database Management**: PostgreSQL runs in Docker. Connection: `postgresql://postgres:postgres@localhost:5432/postgres`
  - Seed/re-seed: `PYTHONPATH=. python data/seeds/create_seed_db.py`
  - List tables: `docker exec da-agent-postgres psql -U postgres -c "\dt"`
  - Query data: `docker exec da-agent-postgres psql -U postgres -c "SELECT COUNT(*) FROM online_retail"`
- **Trace Logs**: Traces are saved to `evals/reports/traces.jsonl`. Monitor for real-time agent execution details.

## Common Issues and Fixes

### PostgreSQL not running
```bash
docker compose up -d postgres
# Verify:
docker exec da-agent-postgres psql -U postgres -c "SELECT 1"
```

### Connection refused to PostgreSQL
- Check container is running: `docker ps | grep postgres`
- Check port 5432 is available: `lsof -i :5432`
- Reset PostgreSQL data: `docker compose down -v && docker compose up -d postgres`

### Seed script fails with "module not found"
```bash
# Always set PYTHONPATH when running seed script:
PYTHONPATH=. python data/seeds/create_seed_db.py
```

### Tests failing with "Unknown table" errors
If running in WSL, ensure paths are correctly normalized. Spider eval cases use POSIX-style paths to locate SQLite database files (Spider uses SQLite, not PostgreSQL).

### Langfuse Prompt Fetching Warnings
You may see warnings like `Langfuse.get_prompt() got an unexpected keyword argument 'labels'`. Non-blocking — system falls back to local prompt templates.

### Streamlit UI Not Updating
Check terminal output for LangGraph execution errors. Run with `uv run streamlit run streamlit_app.py`.

## Database Architecture

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Main database | PostgreSQL 15 (Docker) | User data, uploaded CSVs, query results |
| Spider eval databases | SQLite (files) | Spider benchmark evaluation only |
| Conversation memory | SQLite (local) | Session history |

## Monitoring

- **Evaluations**: Run evaluation suite to monitor SQL validity, routing accuracy, hallucination risks:
  ```bash
  uv run python -m evals.runner --suite spider --split dev
  ```
- **Langfuse**: If configured, monitor traces and generations in the Langfuse dashboard for detailed observability.
- **PostgreSQL logs**: `docker compose logs -f postgres`
