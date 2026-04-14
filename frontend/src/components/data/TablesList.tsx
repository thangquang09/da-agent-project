"use client";

import { useEffect, useMemo, useState } from "react";
import { useChatStore } from "@/stores/chatStore";
import { Table2, Columns, FileText, ChevronDown, ChevronUp, Trash2, AlertCircle } from "lucide-react";

const TABLE_LIMIT = 3;

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
  const updateTableContext = useChatStore((s) => s.updateTableContext);
  const dropTable = useChatStore((s) => s.dropTable);
  const [expandedTable, setExpandedTable] = useState<string | null>(null);
  const [editingContext, setEditingContext] = useState<string>("");
  const [confirmDrop, setConfirmDrop] = useState<string | null>(null);
  const [dropping, setDropping] = useState<string | null>(null);

  useEffect(() => {
    fetchTables();
  }, [fetchTables]);

  // Filter out system tables
  const userTables = useMemo(() => {
    return availableTables.filter((t) => !SYSTEM_TABLES.has(t.table_name));
  }, [availableTables]);

  const slotsUsed = userTables.length;
  const slotsRemaining = TABLE_LIMIT - slotsUsed;

  const toggleExpand = (tableName: string, currentContext: string) => {
    if (expandedTable === tableName) {
      setExpandedTable(null);
      setEditingContext("");
    } else {
      setExpandedTable(tableName);
      setEditingContext(currentContext || "");
    }
  };

  const handleContextSave = async (tableName: string) => {
    await updateTableContext(tableName, editingContext.trim());
    setExpandedTable(null);
    setEditingContext("");
  };

  const handleContextKeyDown = (e: React.KeyboardEvent, tableName: string) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleContextSave(tableName);
    }
    if (e.key === "Escape") {
      setExpandedTable(null);
      setEditingContext("");
    }
  };

  const handleDropConfirm = async (tableName: string) => {
    setDropping(tableName);
    await dropTable(tableName);
    setDropping(null);
    setConfirmDrop(null);
  };

  if (userTables.length === 0) {
    return (
      <div className="text-center py-8">
        <Table2 size={32} className="mx-auto text-slate-300 dark:text-slate-600 mb-3" />
        <p className="text-sm text-slate-500 dark:text-slate-400">No tables available</p>
        <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">
          Upload CSV files to create tables
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {/* Header + slot indicator */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-slate-700 dark:text-slate-200">
          Available Tables
        </h3>
        <span
          className={`text-xs px-2 py-0.5 rounded-full font-medium ${
            slotsRemaining === 0
              ? "bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400"
              : slotsRemaining === 1
              ? "bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400"
              : "bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400"
          }`}
        >
          {slotsUsed}/{TABLE_LIMIT} slots
        </span>
      </div>

      {/* Limit warning */}
      {slotsRemaining === 0 && (
        <div className="flex items-center gap-2 p-2.5 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 mb-3">
          <AlertCircle size={14} className="text-amber-500 shrink-0" />
          <p className="text-xs text-amber-700 dark:text-amber-300">
            Đã đạt giới hạn 3 bảng. Xóa bảng cũ trước khi tải lên file mới.
          </p>
        </div>
      )}

      <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
        {userTables.map((table) => {
          const isExpanded = expandedTable === table.table_name;
          const hasContext = !!table.business_context;
          const isConfirming = confirmDrop === table.table_name;
          const isDropping = dropping === table.table_name;

          return (
            <div
              key={table.table_name}
              className="rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 overflow-hidden"
            >
              {/* Table header */}
              <div className="p-3">
                <div className="flex items-center gap-2 mb-2">
                  <Table2 size={14} className="text-indigo-500 shrink-0" />
                  <span className="text-sm font-medium text-slate-800 dark:text-slate-100 truncate flex-1">
                    {table.table_name}
                  </span>
                  {hasContext && (
                    <FileText size={12} className="text-amber-500 shrink-0" />
                  )}
                  {table.row_count !== undefined && (
                    <span className="text-xs text-slate-500 dark:text-slate-400 shrink-0">
                      {table.row_count.toLocaleString()} rows
                    </span>
                  )}

                  {/* Drop button */}
                  {!isConfirming ? (
                    <button
                      onClick={() => setConfirmDrop(table.table_name)}
                      disabled={isDropping}
                      title="Xóa bảng này"
                      className="p-1 rounded hover:bg-red-100 dark:hover:bg-red-900/30 text-slate-400 hover:text-red-500 transition-colors disabled:opacity-50"
                    >
                      <Trash2 size={13} />
                    </button>
                  ) : (
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => void handleDropConfirm(table.table_name)}
                        disabled={isDropping}
                        className="text-[11px] px-1.5 py-0.5 rounded bg-red-500 text-white hover:bg-red-600 disabled:opacity-50"
                      >
                        {isDropping ? "…" : "Xóa"}
                      </button>
                      <button
                        onClick={() => setConfirmDrop(null)}
                        className="text-[11px] px-1.5 py-0.5 rounded text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700"
                      >
                        Hủy
                      </button>
                    </div>
                  )}
                </div>

                {table.columns.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {table.columns.slice(0, 4).map((col) => (
                      <span
                        key={col.name}
                        className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300"
                      >
                        <Columns size={10} className="text-slate-400" />
                        {col.name}
                      </span>
                    ))}
                    {table.columns.length > 4 && (
                      <span className="text-xs text-slate-500 dark:text-slate-400 px-2 py-0.5">
                        +{table.columns.length - 4} more
                      </span>
                    )}
                  </div>
                )}
              </div>

              {/* Context row */}
              <button
                onClick={() => toggleExpand(table.table_name, table.business_context || "")}
                className="w-full flex items-center gap-1.5 px-3 py-1.5 text-xs border-t border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              >
                <FileText size={11} className={hasContext ? "text-amber-500" : "text-slate-400"} />
                <span className={hasContext ? "text-slate-600 dark:text-slate-300" : "text-slate-400 dark:text-slate-500"}>
                  {hasContext
                    ? table.business_context!.substring(0, 60) + (table.business_context!.length > 60 ? "..." : "")
                    : "Add business context..."}
                </span>
                <span className="ml-auto">
                  {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                </span>
              </button>

              {/* Expanded context editor */}
              {isExpanded && (
                <div className="p-3 border-t border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
                  <textarea
                    placeholder="Describe what this data is about, its domain, key metrics..."
                    value={editingContext}
                    onChange={(e) => setEditingContext(e.target.value)}
                    onKeyDown={(e) => handleContextKeyDown(e, table.table_name)}
                    rows={3}
                    autoFocus
                    className="w-full text-xs p-2 rounded border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-700 dark:text-slate-200 placeholder:text-slate-400 dark:placeholder:text-slate-500 resize-none focus:outline-none focus:ring-1 focus:ring-indigo-400"
                  />
                  <div className="flex justify-end gap-2 mt-2">
                    <button
                      onClick={() => { setExpandedTable(null); setEditingContext(""); }}
                      className="text-xs px-2 py-1 rounded text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={() => void handleContextSave(table.table_name)}
                      className="text-xs px-3 py-1 rounded bg-indigo-500 text-white hover:bg-indigo-600 transition-colors"
                    >
                      Save
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
