"""Migration 002: Create `agent` and `user_data` schemas.

Separates internal agent state from user-uploaded data tables
within the same PostgreSQL database.
"""

from __future__ import annotations

from app.config import load_settings
from app.logger import logger

SQL = """
CREATE SCHEMA IF NOT EXISTS agent;
CREATE SCHEMA IF NOT EXISTS user_data;
"""


def run() -> None:
    """Execute the schema creation migration."""
    settings = load_settings()

    import psycopg

    with psycopg.connect(settings.database_url) as conn:
        conn.execute(SQL)
        conn.commit()

    logger.info("Migration 002 applied: agent + user_data schemas created")


if __name__ == "__main__":
    run()
    print("Migration 002 applied: agent + user_data schemas created")
