from __future__ import annotations

"""User-scoped operations: cleanup and table listing."""

import re
from typing import Any

import psycopg
from fastapi import APIRouter, Response, status

from app.config import load_settings
from app.logger import logger
from app.tools.table_metadata import (
    cleanup_expired_tables,
    delete_all_user_contexts,
    get_user_table_names,
)

router = APIRouter(prefix="/users", tags=["users"])

_MAX_TABLES_PER_USER = 3


def _is_valid_user_id(user_id: str) -> bool:
    """Basic validation: alphanumeric + underscore, max 80 chars."""
    return bool(re.match(r"^[a-z0-9_]{1,80}$", user_id))


@router.get("/{user_id}/tables")
async def list_user_tables(user_id: str) -> dict[str, Any]:
    """List all tables owned by a user, with count and limit info."""
    if not _is_valid_user_id(user_id):
        return {"tables": [], "count": 0, "limit": _MAX_TABLES_PER_USER, "user_id": user_id}

    logger.info("users GET /users/{uid}/tables", uid=user_id)

    # Lazy TTL cleanup — drop tables older than 2 hours
    try:
        cleanup_expired_tables()
    except Exception:  # noqa: BLE001
        pass
    table_names = get_user_table_names(user_id)

    return {
        "user_id": user_id,
        "tables": table_names,
        "count": len(table_names),
        "limit": _MAX_TABLES_PER_USER,
        "slots_remaining": max(0, _MAX_TABLES_PER_USER - len(table_names)),
    }


@router.post("/{user_id}/cleanup")
async def cleanup_user_tables(user_id: str, response: Response) -> dict[str, Any]:
    """Drop all PostgreSQL tables owned by user_id and remove their contexts.

    Called by frontend via navigator.sendBeacon on session end, or explicitly
    on logout. Safe to call multiple times (idempotent).
    """
    if not _is_valid_user_id(user_id):
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {"error": "invalid_user_id", "dropped": [], "count": 0}

    logger.info("users POST /users/{uid}/cleanup — dropping tables", uid=user_id)

    table_names = get_user_table_names(user_id)
    dropped: list[str] = []
    errors: list[str] = []

    if table_names:
        settings = load_settings()
        try:
            with psycopg.connect(settings.database_url) as conn:
                for table_name in table_names:
                    try:
                        conn.execute(f'DROP TABLE IF EXISTS public."{table_name}" CASCADE')
                        dropped.append(table_name)
                        logger.info(
                            "users cleanup dropped table={table} for user={uid}",
                            table=table_name,
                            uid=user_id,
                        )
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"{table_name}: {exc}")
                        logger.warning(
                            "users cleanup failed to drop table={table}: {err}",
                            table=table_name,
                            err=str(exc),
                        )
        except Exception as exc:  # noqa: BLE001
            logger.error("users cleanup db connection failed for uid={uid}: {err}", uid=user_id, err=str(exc))
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"error": str(exc), "dropped": dropped, "count": len(dropped)}

    # Remove contexts regardless (idempotent cleanup)
    delete_all_user_contexts(user_id)

    logger.info(
        "users cleanup complete uid={uid} dropped={n} errors={e}",
        uid=user_id,
        n=len(dropped),
        e=len(errors),
    )

    return {
        "user_id": user_id,
        "dropped": dropped,
        "count": len(dropped),
        "errors": errors,
    }
