from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.logger import logger
from app.tools.auto_register import auto_register_csv
from app.tools.get_schema import describe_table, list_tables

router = APIRouter(prefix="/data", tags=["data"])


@router.post("/upload")
async def upload_files(
    files: list[UploadFile] = File(default=[]),
) -> dict[str, Any]:
    """
    Upload and process CSV files into database tables.

    Returns:
        - registered_tables: list of successfully registered table names
        - errors: list of processing errors
        - tables: detailed info for each registered table
    """
    logger.info("backend.data POST /upload files={n}", n=len(files))

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
        table_name = Path(filename).stem

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
    List all available tables in the database with their schema.

    Returns:
        - tables: list of table info with name, columns, row count
        - count: total number of tables
    """
    logger.info("backend.data GET /tables")

    table_names = list_tables()
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
            }
        )

    return {
        "tables": tables,
        "count": len(tables),
    }
