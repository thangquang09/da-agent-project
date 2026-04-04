from __future__ import annotations

import html
from dataclasses import dataclass

DEFAULT_CONTEXT = "No business context provided."


@dataclass
class TableEntry:
    """A registered table with its compact schema and user-provided business context."""

    table_name: str
    schema: str          # "col_name TYPE, col_name TYPE, ..." compact form
    business_context: str


def format_schema_columns(columns: list[dict]) -> str:
    """
    Convert a columns list to a compact schema string.

    Accepts dicts from either auto_register (dtype key) or
    get_schema_overview (type key):
        [{"name": "id", "type": "INTEGER"}, ...]
        [{"name": "id", "dtype": "integer"}, ...]
    """
    parts: list[str] = []
    for col in columns:
        name = col.get("name", "")
        col_type = (
            col.get("type")
            or col.get("col_type")
            or col.get("dtype")
            or "TEXT"
        )
        parts.append(f"{name} {str(col_type).upper()}")
    return ", ".join(parts)


def build_xml_entry(entry: TableEntry) -> str:
    """Render a single TableEntry as an XML block."""
    ctx = html.escape(entry.business_context.strip() or DEFAULT_CONTEXT)
    table_name = html.escape(entry.table_name, quote=True)
    schema = html.escape(entry.schema)
    return (
        f'<table name="{table_name}">\n'
        f"  <schema>{schema}</schema>\n"
        f"  <business_context>{ctx}</business_context>\n"
        f"</table>"
    )


def build_full_xml_context(entries: list[TableEntry]) -> str:
    """
    Combine all TableEntry blocks into a single <database_context> XML string.

    Returns empty string when entries list is empty.
    """
    if not entries:
        return ""
    blocks = "\n".join(build_xml_entry(e) for e in entries)
    return f"<database_context>\n{blocks}\n</database_context>"
