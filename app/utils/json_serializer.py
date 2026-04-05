from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


def result_to_json(obj: Any) -> str | float | None:
    """Custom serializer for SQL result types that json.dumps cannot handle."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def safe_json_dumps(data: Any, **kwargs: Any) -> str:
    """JSON dumps with custom serializer for SQL result types."""
    return json.dumps(data, default=result_to_json, **kwargs)


def safe_json_loads(text: str, **kwargs: Any) -> Any:
    """Standard JSON loads (no special handling needed for parsing)."""
    return json.loads(text, **kwargs)
