"""SQL error classification for retry logic."""

from __future__ import annotations

import sqlite3
from typing import Literal

ErrorCategory = Literal["retryable", "non_retryable", "unknown"]


def classify_sql_error(error: Exception) -> ErrorCategory:
    """Classify SQL errors as retryable or non-retryable.

    Retryable: Logic/syntax errors that LLM can potentially fix
    Non-retryable: Systemic errors that LLM cannot fix

    Args:
        error: The exception that occurred during SQL execution

    Returns:
        Category of error: "retryable", "non_retryable", or "unknown"

    Example:
        >>> try:
        ...     cursor.execute("SELECT * FROM nonexistent")
        ... except sqlite3.OperationalError as e:
        ...     classify_sql_error(e)
        'retryable'
    """
    error_str = str(error).lower()
    error_type = type(error).__name__

    # Retryable: Syntax/logic errors (check before DatabaseError since OperationalError is a subclass)
    if isinstance(error, sqlite3.OperationalError):
        return "retryable"

    # Non-retryable: Systemic/permission issues
    if isinstance(error, (sqlite3.DatabaseError, sqlite3.IntegrityError)):
        return "non_retryable"

    if any(
        keyword in error_str
        for keyword in [
            "database disk image is malformed",
            "disk i/o error",
            "permission denied",
            "unable to open database",
            "readonly database",
        ]
    ):
        return "non_retryable"

    if any(
        keyword in error_str
        for keyword in [
            "syntax error",
            "no such column",
            "no such table",
            "ambiguous column",
            "misuse of aggregate",
        ]
    ):
        return "retryable"

    # Validation errors from our guardrail
    if "validation" in error_str or "validation_reasons" in error_str:
        return "retryable"

    return "unknown"
