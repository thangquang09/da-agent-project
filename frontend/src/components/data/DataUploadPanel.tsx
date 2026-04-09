"use client";

import { useChatStore } from "@/stores/chatStore";
import { FileUploader } from "./FileUploader";
import { TablesList } from "./TablesList";
import { X, Database } from "lucide-react";

export function DataUploadPanel() {
  const dataPanelOpen = useChatStore((s) => s.dataPanelOpen);
  const toggleDataPanel = useChatStore((s) => s.toggleDataPanel);

  if (!dataPanelOpen) {
    return null;
  }

  return (
    <div className="w-[320px] min-w-[320px] h-full bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-800 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-800">
        <div className="flex items-center gap-2">
          <Database size={18} className="text-indigo-500" />
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            Data Management
          </h2>
        </div>
        <button
          onClick={toggleDataPanel}
          className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
          aria-label="Close data panel"
        >
          <X size={16} />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {/* Upload section */}
        <div>
          <h3 className="text-xs font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3">
            Upload Files
          </h3>
          <FileUploader />
        </div>

        {/* Tables section */}
        <div>
          <TablesList />
        </div>
      </div>
    </div>
  );
}