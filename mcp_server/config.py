from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import load_settings


@dataclass(frozen=True)
class MCPConfig:
    db_path: Path
    max_limit: int
    sample_rows: int
    top_values: int


def load_mcp_config() -> MCPConfig:
    settings = load_settings()
    return MCPConfig(
        db_path=Path(settings.sqlite_db_path),
        max_limit=int(200),
        sample_rows=3,
        top_values=3,
    )

