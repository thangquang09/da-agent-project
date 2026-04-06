"use client";

import { useChatStore } from "@/stores/chatStore";
import type { ReportArtifactData } from "@/lib/types";
import { X } from "lucide-react";
import { ReportView } from "@/components/artifact/ReportView";
import { SqlView } from "@/components/artifact/SqlView";
import { ChartView } from "@/components/artifact/ChartView";
import { TraceTimeline } from "@/components/artifact/TraceTimeline";

export function ArtifactPanel() {
  const content = useChatStore((s) => s.artifactContent);
  const closeArtifact = useChatStore((s) => s.closeArtifact);

  if (!content) return null;

  const tabLabel: Record<string, string> = {
    report: "Report",
    sql: "SQL",
    chart: "Chart",
    trace: "Trace",
  };

  const panelWidthClass =
    content.type === "report"
      ? "w-[560px] min-w-[560px]"
      : content.type === "trace"
      ? "w-[600px] min-w-[600px]"
      : "w-[480px] min-w-[480px]";

  return (
    <aside className={`flex h-full flex-col border-l border-slate-200 bg-slate-50 ${panelWidthClass}`}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-200 bg-white">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-slate-700">
            {tabLabel[content.type] ?? "Artifact"}
          </span>
          {content.title && (
            <span className="text-xs text-slate-400 truncate max-w-[200px]">
              &mdash; {content.title}
            </span>
          )}
        </div>
        <button
          onClick={closeArtifact}
          className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
          aria-label="Close artifact panel"
        >
          <X size={18} />
        </button>
      </div>

      {/* Content */}
      <div className={`flex-1 min-h-0 ${content.type === "trace" ? "overflow-hidden" : "overflow-y-auto p-5"}`}>
        {content.type === "report" && (
          <ReportView report={content.data as ReportArtifactData} />
        )}
        {content.type === "sql" && (
          <SqlView sql={content.data as string} />
        )}
        {content.type === "chart" && (
          <ChartView imageData={content.data as string} />
        )}
        {content.type === "trace" && (
          <TraceTimeline runId={content.data as string} />
        )}
      </div>
    </aside>
  );
}
