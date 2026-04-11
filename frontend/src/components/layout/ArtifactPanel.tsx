"use client";

import { useChatStore } from "@/stores/chatStore";
import type { ReportArtifactData } from "@/lib/types";
import { X } from "lucide-react";
import { ReportView } from "@/components/artifact/ReportView";
import { SqlView } from "@/components/artifact/SqlView";
import { ChartView } from "@/components/artifact/ChartView";
import { TraceTimeline } from "@/components/artifact/TraceTimeline";
import { useState, useCallback, useRef, useEffect } from "react";

const DEFAULT_WIDTHS: Record<string, number> = {
  report: 560,
  trace: 600,
  sql: 480,
  chart: 480,
};

const MIN_WIDTH = 360;
const MAX_WIDTH = 1200;

export function ArtifactPanel() {
  const content = useChatStore((s) => s.artifactContent);
  const closeArtifact = useChatStore((s) => s.closeArtifact);

  const [panelWidth, setPanelWidth] = useState<number>(
    DEFAULT_WIDTHS[content?.type ?? "sql"]
  );
  const isDragging = useRef(false);
  const startX = useRef(0);
  const startWidth = useRef(0);

  // Reset width when artifact type changes
  useEffect(() => {
    if (content?.type) {
      setPanelWidth(DEFAULT_WIDTHS[content.type] ?? 480);
    }
  }, [content?.type]);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      isDragging.current = true;
      startX.current = e.clientX;
      startWidth.current = panelWidth;
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    },
    [panelWidth]
  );

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging.current) return;
      // Dragging left edge: moving mouse left increases width
      const delta = startX.current - e.clientX;
      const newWidth = Math.min(
        MAX_WIDTH,
        Math.max(MIN_WIDTH, startWidth.current + delta)
      );
      setPanelWidth(newWidth);
    };

    const handleMouseUp = () => {
      if (!isDragging.current) return;
      isDragging.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, []);

  if (!content) return null;

  const tabLabel: Record<string, string> = {
    report: "Report",
    sql: "SQL",
    chart: "Chart",
    trace: "Trace",
  };

  return (
    <aside
      className="relative flex h-full flex-col border-l border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900"
      style={{ width: panelWidth, minWidth: MIN_WIDTH, maxWidth: MAX_WIDTH }}
    >
      {/* ── Drag handle (left edge) ── */}
      <div
        onMouseDown={handleMouseDown}
        className="resize-handle absolute left-0 top-0 h-full z-20"
        title="Drag to resize"
      />

      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">
            {tabLabel[content.type] ?? "Artifact"}
          </span>
          {content.title && (
            <span className="text-xs text-slate-400 dark:text-slate-500 truncate max-w-[200px]">
              &mdash; {content.title}
            </span>
          )}
        </div>
        <button
          onClick={closeArtifact}
          className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
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
          <ChartView imageUrl={content.data as string} />
        )}
        {content.type === "trace" && (
          <TraceTimeline runId={content.data as string} />
        )}
      </div>
    </aside>
  );
}
