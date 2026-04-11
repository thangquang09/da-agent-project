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
    <div className="w-[320px] min-w-[320px] h-full bg-[#f7f6f3] dark:bg-[#1b1b1b] border-l border-[#dfddd7] dark:border-[#2b2b2b] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#dfddd7] dark:border-[#2b2b2b]">
        <div className="flex items-center gap-2">
          <Database size={18} className="text-[#5f5f5f] dark:text-[#c9c9c9]" />
          <h2 className="text-sm font-semibold text-[#353535] dark:text-[#efefef]">
            Data Management
          </h2>
        </div>
        <button
          onClick={toggleDataPanel}
          className="p-1.5 rounded-lg hover:bg-[#ece9e2] dark:hover:bg-[#282828] text-[#7d7d7d] hover:text-[#2f2f2f] dark:text-[#a1a1a1] dark:hover:text-[#ececec] transition-colors"
          aria-label="Close data panel"
        >
          <X size={16} />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {/* Upload section */}
        <div>
          <h3 className="text-xs font-medium uppercase tracking-wider text-[#888888] dark:text-[#a3a3a3] mb-3">
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
