from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.logger import logger
from app.tools.auto_context import auto_generate_table_context
from app.tools.auto_register import auto_register_csv
from app.tools.get_schema import describe_table, list_tables
from app.tools.table_metadata import (
    delete_table_context,
    get_all_table_contexts,
    get_table_context,
    set_table_context,
)

router = APIRouter(prefix="/data", tags=["data"])


def _normalize_table_name(raw_name: str) -> str:
    """Normalize a filename stem into a safe PostgreSQL table name."""
    name = re.sub(r"[^a-zA-Z0-9_]", "_", raw_name).strip("_")
    if not name or not name[0].isalpha():
        name = f"table_{name}"
    return name


@router.post("/upload")
async def upload_files(
    files: list[UploadFile] = File(default=[]),
    contexts_json: str = Form(default="{}"),
) -> dict[str, Any]:
    """
    Upload and process CSV files into database tables.

    Optionally attach business context per file via `contexts_json`:
    a JSON string mapping filename -> context text.

    Returns:
        - registered_tables: list of successfully registered table names
        - errors: list of processing errors
        - tables: detailed info for each registered table
    """
    logger.info("backend.data POST /upload files={n}", n=len(files))

    # Parse contexts_json: {filename: business_context}
    try:
        file_contexts: dict[str, str] = json.loads(contexts_json) if contexts_json else {}
    except json.JSONDecodeError:
        file_contexts = {}

    if not files:
        return {
            "registered_tables": [],
            "errors": [],
            "tables": [],
        }

    registered_tables: list[str] = []
    errors: list[dict[str, str]] = []
    tables_info: list[dict[str, Any]] = []

    for f in files:
        filename = f.filename or "upload.csv"
        table_name = _normalize_table_name(Path(filename).stem)
        context = file_contexts.get(filename, "")

        try:
            content = await f.read()

            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".csv", delete=False
            ) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            result, error = auto_register_csv(
                file_path=tmp_path,
                table_name=table_name,
            )

            Path(tmp_path).unlink(missing_ok=True)

            if error:
                errors.append(
                    {
                        "file": filename,
                        "error": error,
                    }
                )
                logger.warning(
                    "backend.data upload failed file={file} error={err}",
                    file=filename,
                    err=error,
                )
            else:
                # Persist business context
                auto_context: str | None = None
                if context:
                    set_table_context(result.table_name, context)
                else:
                    # Auto-generate context if user didn't provide one
                    try:
                        auto_context = auto_generate_table_context(result.table_name)
                    except Exception as exc:
                        logger.warning(
                            "backend.data auto_context failed for table={table}: {error}",
                            table=result.table_name,
                            error=str(exc),
                        )

                registered_tables.append(result.table_name)
                tables_info.append(
                    {
                        "table_name": result.table_name,
                        "row_count": result.row_count,
                        "columns": [
                            {
                                "name": col.get("name"),
                                "type": col.get("type"),
                                "nullable": col.get("nullable", True),
                            }
                            for col in result.columns
                        ],
                        "original_file": filename,
                        "business_context": context,
                        "auto_context": auto_context,
                    }
                )
                logger.info(
                    "backend.data registered file={file} -> table={table} rows={rows}",
                    file=filename,
                    table=result.table_name,
                    rows=result.row_count,
                )

        except Exception as exc:
            errors.append(
                {
                    "file": filename,
                    "error": str(exc),
                }
            )
            logger.exception(
                "backend.data upload error file={file}",
                file=filename,
            )

    return {
        "registered_tables": registered_tables,
        "errors": errors,
        "tables": tables_info,
    }


@router.get("/tables")
async def get_tables() -> dict[str, Any]:
    """
    List all available tables in the database with their schema and business context.

    Returns:
        - tables: list of table info with name, columns, business_context
        - count: total number of tables
    """
    logger.info("backend.data GET /tables")

    table_names = list_tables()
    all_contexts = get_all_table_contexts()
    tables: list[dict[str, Any]] = []

    for name in table_names:
        columns = describe_table(name)
        tables.append(
            {
                "table_name": name,
                "columns": [
                    {
                        "name": col.name,
                        "type": col.col_type,
                        "nullable": col.nullable,
                        "is_primary_key": col.is_pk,
                    }
                    for col in columns
                ],
                "business_context": all_contexts.get(name, ""),
            }
        )

    return {
        "tables": tables,
        "count": len(tables),
    }


@router.put("/tables/{table_name}/context")
async def update_table_context(
    table_name: str,
    body: dict[str, str],
) -> dict[str, Any]:
    """
    Update business context for a specific table.

    Body: {"context": "Business context text here"}
    """
    context = body.get("context", "")
    logger.info(
        "backend.data PUT context for table={table} ({len} chars)",
        table=table_name,
        len=len(context),
    )

    # Validate table exists
    existing = list_tables()
    if table_name not in existing:
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")

    set_table_context(table_name, context)

    return {
        "table_name": table_name,
        "business_context": context,
    }


@router.post("/tables/{table_name}/auto-context")
async def generate_auto_context(table_name: str) -> dict[str, Any]:
    """
    Auto-generate business context for a table using LLM.

    Returns the generated context for user confirmation.
    Context is NOT persisted until user confirms via PUT /tables/{name}/context.
    """
    logger.info("backend.data POST auto-context for table={table}", table=table_name)

    existing = list_tables()
    if table_name not in existing:
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")

    auto_context = auto_generate_table_context(table_name)

    if not auto_context:
        raise HTTPException(
            status_code=422,
            detail="Failed to auto-generate context for this table",
        )

    return {
        "table_name": table_name,
        "auto_context": auto_context,
    }


@router.delete("/tables/{table_name}")
async def drop_table(table_name: str) -> dict[str, Any]:
    """
    Drop a table and its associated business context.
    """
    from app.config import load_settings
    import psycopg

    logger.info("backend.data DELETE table={table}", table=table_name)

    existing = list_tables()
    if table_name not in existing:
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")

    settings = load_settings()
    with psycopg.connect(settings.database_url) as conn:
        conn.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE')

    delete_table_context(table_name)

    return {"deleted": table_name}
