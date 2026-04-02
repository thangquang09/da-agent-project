from __future__ import annotations

import base64
from typing import Any


def make_serializable(obj: Any) -> Any:
    """
    Recursively convert bytes → base64-encoded str for JSON / Pydantic compatibility.

    Context: run_query() returns a payload dict that may contain ``bytes``
    values (e.g. visualization.image_data is a raw PNG).  Pydantic v2 raises
    ``ValidationError`` when it receives non-ASCII bytes for a ``str`` field,
    and ``json.dumps`` also rejects raw bytes.  Applying this helper before
    model construction or serialisation prevents both failures.

    Usage:
        payload = make_serializable(raw_payload)
        return QueryResponse(**{k: v for k, v in payload.items() ...})
    """
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode()
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [make_serializable(i) for i in obj]
    return obj
