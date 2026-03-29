from __future__ import annotations

import pytest

from app.config import load_settings
from data.seeds.create_seed_db import main as seed_main


@pytest.fixture(scope="session", autouse=True)
def seeded_sqlite_db():
    load_settings.cache_clear()
    seed_main()
    yield
    load_settings.cache_clear()

