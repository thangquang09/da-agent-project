from __future__ import annotations

import base64
from typing import Any


def make_serializable(obj: Any) -> Any:
    """Recursively convert bytes → base64-encoded str for JSON / Pydantic compatibility.

    Heavy data (chart PNGs, report markdown) is now stored on disk and referenced
    by URL. This helper only handles stray bytes values that might still appear
    (e.g., uploaded file data in memory, Decimal values from SQL results).
    """
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode()
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [make_serializable(i) for i in obj]
    return obj
