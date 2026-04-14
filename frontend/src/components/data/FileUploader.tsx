"use client";

import { useCallback, useState } from "react";
import { useChatStore } from "@/stores/chatStore";
import { uploadFiles as uploadFilesAPI } from "@/lib/api";
import { Upload, CheckCircle, AlertCircle, Loader2, Bot, Pencil, Check } from "lucide-react";
import type { TableInfo } from "@/lib/types";

interface PendingTable {
  table_name: string;
  business_context: string;
  auto_context?: string;
  editing: boolean; // true = user is editing the auto-suggested context
  confirmed: boolean; // true = user accepted the auto context
}

export function FileUploader() {
  const [dragActive, setDragActive] = useState(false);
  const [pendingTables, setPendingTables] = useState<PendingTable[]>([]);
  const uploadStatus = useChatStore((s) => s.uploadStatus);
  const uploadError = useChatStore((s) => s.uploadError);
  const storeUploadFiles = useChatStore((s) => s.uploadFiles);
  const updateTableContext = useChatStore((s) => s.updateTableContext);
  const fetchTables = useChatStore((s) => s.fetchTables);
  const userId = useChatStore((s) => s.userId);

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  }, []);

  const processFiles = useCallback(
    async (files: FileList) => {
      const fileArray: { name: string; data: ArrayBuffer; context: string }[] = [];

      for (const file of Array.from(files)) {
        if (file.name.endsWith(".csv") || file.name.endsWith(".xlsx") || file.name.endsWith(".xls")) {
          const data = await file.arrayBuffer();
          fileArray.push({ name: file.name, data, context: "" });
        }
      }

      if (fileArray.length > 0) {
        storeUploadFiles(fileArray);

        try {
          const response = await uploadFilesAPI(fileArray, userId ?? undefined);
          if (response.tables && response.tables.length > 0) {
            setPendingTables(
              response.tables.map((t: TableInfo) => ({
                table_name: t.table_name,
                business_context: t.auto_context || t.business_context || "",
                auto_context: t.auto_context || undefined,
                editing: false,
                confirmed: !t.auto_context, // If no auto_context, nothing to confirm
              }))
            );
          }
        } catch {
          // Error already handled by store
        }
      }
    },
    [storeUploadFiles, userId]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragActive(false);

      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        processFiles(e.dataTransfer.files);
      }
    },
    [processFiles]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files.length > 0) {
        processFiles(e.target.files);
      }
    },
    [processFiles]
  );

  const handleContextChange = (tableName: string, value: string) => {
    setPendingTables((prev) =>
      prev.map((t) => (t.table_name === tableName ? { ...t, business_context: value } : t))
    );
  };

  const handleContextSave = async (tableName: string, context: string) => {
    if (context.trim()) {
      await updateTableContext(tableName, context.trim());
    }
  };

  const handleContextKeyDown = (e: React.KeyboardEvent, tableName: string, context: string) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleContextSave(tableName, context);
    }
  };

  const handleConfirmAutoContext = async (tableName: string, context: string) => {
    await handleContextSave(tableName, context);
    setPendingTables((prev) =>
      prev.map((t) => (t.table_name === tableName ? { ...t, confirmed: true } : t))
    );
  };

  const handleEditAutoContext = (tableName: string) => {
    setPendingTables((prev) =>
      prev.map((t) => (t.table_name === tableName ? { ...t, editing: true } : t))
    );
  };

  const dismissPending = () => {
    setPendingTables([]);
    fetchTables();
  };

  const isUploading = uploadStatus === "uploading";

  return (
    <div className="space-y-3">
      <div
        className={`
          relative border-2 border-dashed rounded-xl p-6 transition-colors
          ${dragActive ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950/30" : "border-slate-300 dark:border-slate-700"}
          ${isUploading ? "opacity-60 pointer-events-none" : "hover:border-slate-400 dark:hover:border-slate-600"}
        `}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
      >
        <input
          type="file"
          accept=".csv,.xlsx,.xls"
          multiple
          onChange={handleChange}
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
          disabled={isUploading}
        />

        <div className="flex flex-col items-center gap-2 text-center">
          {isUploading ? (
            <>
              <Loader2 size={24} className="text-indigo-500 animate-spin" />
              <p className="text-sm text-slate-600 dark:text-slate-300">
                Processing files...
              </p>
            </>
          ) : (
            <>
              <Upload size={24} className="text-slate-400" />
              <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
                Drop CSV or Excel files here
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                or click to browse
              </p>
            </>
          )}
        </div>
      </div>

      {/* Pending tables - context input / auto-context confirmation after upload */}
      {pendingTables.length > 0 && uploadStatus === "success" && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Business Context
            </p>
            <button
              onClick={dismissPending}
              className="text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
            >
              Done
            </button>
          </div>
          {pendingTables.map((table) => (
            <div
              key={table.table_name}
              className={`p-3 rounded-lg border ${
                table.confirmed
                  ? "bg-emerald-50 dark:bg-emerald-950/20 border-emerald-200 dark:border-emerald-800"
                  : table.auto_context
                    ? "bg-amber-50 dark:bg-amber-950/20 border-amber-200 dark:border-amber-800"
                    : "bg-indigo-50 dark:bg-indigo-950/20 border-indigo-200 dark:border-indigo-800"
              }`}
            >
              <div className="flex items-center gap-2 mb-2">
                {table.confirmed ? (
                  <CheckCircle size={14} className="text-emerald-600 dark:text-emerald-400 shrink-0" />
                ) : table.auto_context ? (
                  <Bot size={14} className="text-amber-600 dark:text-amber-400 shrink-0" />
                ) : null}
                <p className={`text-xs font-medium ${
                  table.confirmed
                    ? "text-emerald-700 dark:text-emerald-300"
                    : table.auto_context
                      ? "text-amber-700 dark:text-amber-300"
                      : "text-indigo-700 dark:text-indigo-300"
                }`}>
                  {table.table_name}
                </p>
              </div>

              {/* Auto-context suggestion card */}
              {table.auto_context && !table.confirmed && !table.editing && (
                <div className="space-y-2">
                  <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed">
                    {table.auto_context}
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleConfirmAutoContext(table.table_name, table.auto_context!)}
                      className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-md bg-amber-600 text-white hover:bg-amber-700 transition-colors"
                    >
                      <Check size={12} />
                      Tiếp tục
                    </button>
                    <button
                      onClick={() => handleEditAutoContext(table.table_name)}
                      className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-md border border-slate-300 dark:border-slate-600 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                    >
                      <Pencil size={12} />
                      Sửa mô tả
                    </button>
                  </div>
                </div>
              )}

              {/* Confirmed or no auto-context: show textarea */}
              {(table.confirmed || !table.auto_context || table.editing) && (
                <textarea
                  placeholder="Mô tả ngữ cảnh business của data — không bắt buộc nhưng giúp AI phân tích chính xác hơn. Vd: Customer purchase data Q1 2024, dùng để phân tích churn..."
                  value={table.business_context}
                  onChange={(e) => handleContextChange(table.table_name, e.target.value)}
                  onBlur={() => handleContextSave(table.table_name, table.business_context)}
                  onKeyDown={(e) => handleContextKeyDown(e, table.table_name, table.business_context)}
                  rows={2}
                  className="w-full text-xs p-2 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-200 placeholder:text-slate-400 dark:placeholder:text-slate-500 resize-none focus:outline-none focus:ring-1 focus:ring-indigo-400"
                />
              )}

              {table.confirmed && (
                <p className="text-xs text-emerald-600 dark:text-emerald-400 mt-1">
                  Context saved
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {uploadStatus === "success" && pendingTables.length === 0 && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300">
          <CheckCircle size={16} />
          <span className="text-sm">Files uploaded successfully</span>
        </div>
      )}

      {uploadStatus === "error" && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-red-50 dark:bg-red-950/30 text-red-700 dark:text-red-300">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <div className="text-sm">
            <p className="font-medium">Upload failed</p>
            <p className="text-xs opacity-80">{uploadError}</p>
          </div>
        </div>
      )}
    </div>
  );
}
