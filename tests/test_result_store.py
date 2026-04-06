from __future__ import annotations

from decimal import Decimal

from app.tools.result_store import ResultStore


def test_result_store_make_json_safe_converts_decimal() -> None:
    from app.tools.result_store import _decimal_to_serializable

    from decimal import Decimal

    safe = _decimal_to_serializable(
        {
            "value": Decimal("66.082"),
            "rows": [{"avg": Decimal("1.5")}],
        }
    )

    assert safe == {
        "value": 66.082,
        "rows": [{"avg": 1.5}],
    }
