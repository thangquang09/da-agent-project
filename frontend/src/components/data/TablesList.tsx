"use client";

import { useEffect, useMemo } from "react";
import { useChatStore } from "@/stores/chatStore";
import { Table2, Columns } from "lucide-react";

// System tables that should not be shown to users
const SYSTEM_TABLES = new Set([
  "result_store",
  "conversation_turns",
  "conversation_summaries",
  "turn_artifacts",
]);

export function TablesList() {
  const availableTables = useChatStore((s) => s.availableTables);
  const fetchTables = useChatStore((s) => s.fetchTables);

  useEffect(() => {
    fetchTables();
  }, [fetchTables]);

  // Filter out system tables
  const userTables = useMemo(() => {
    return availableTables.filter((t) => !SYSTEM_TABLES.has(t.table_name));
  }, [availableTables]);

  if (userTables.length === 0) {
    return (
      <div className="text-center py-8">
        <Table2 size={32} className="mx-auto text-slate-300 dark:text-slate-600 mb-3" />
        <p className="text-sm text-slate-500 dark:text-slate-400">
          No tables available
        </p>
        <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">
          Upload CSV files to create tables
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-slate-700 dark:text-slate-200">
          Available Tables
        </h3>
        <span className="text-xs text-slate-500 dark:text-slate-400">
          {userTables.length} table{userTables.length !== 1 ? "s" : ""}
        </span>
      </div>

      <div className="space-y-2 max-h-[300px] overflow-y-auto pr-1">
        {userTables.map((table) => (
          <div
            key={table.table_name}
            className="p-3 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700"
          >
            <div className="flex items-center gap-2 mb-2">
              <Table2 size={14} className="text-indigo-500" />
              <span className="text-sm font-medium text-slate-800 dark:text-slate-100">
                {table.table_name}
              </span>
              {table.row_count !== undefined && (
                <span className="text-xs text-slate-500 dark:text-slate-400 ml-auto">
                  {table.row_count.toLocaleString()} rows
                </span>
              )}
            </div>

            {table.columns.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {table.columns.slice(0, 5).map((col) => (
                  <span
                    key={col.name}
                    className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300"
                  >
                    <Columns size={10} className="text-slate-400" />
                    {col.name}
                    <span className="text-slate-400 dark:text-slate-500">
                      ({col.type})
                    </span>
                  </span>
                ))}
                {table.columns.length > 5 && (
                  <span className="text-xs text-slate-500 dark:text-slate-400 px-2 py-0.5">
                    +{table.columns.length - 5} more
                  </span>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}