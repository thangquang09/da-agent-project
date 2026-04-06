"""Migration 001: Create result_store table in PostgreSQL (agent schema).

DEPRECATED: result_store table is now created automatically by
ResultStore._ensure_table_exists() on first use.

This file is kept for historical reference only. The table lives in
the `agent` schema: agent.result_store
"""
