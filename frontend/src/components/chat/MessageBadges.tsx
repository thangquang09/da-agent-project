"use client";

import type { QueryResponse } from "@/lib/types";

interface MessageBadgesProps {
  result: QueryResponse;
}

const intentColors: Record<string, string> = {
  sql: "bg-blue-100 dark:bg-blue-900/40 text-blue-800 dark:text-blue-300",
  rag: "bg-purple-100 dark:bg-purple-900/40 text-purple-800 dark:text-purple-300",
  mixed: "bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300",
  unknown: "bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400",
};

const confidenceColors: Record<string, string> = {
  high: "bg-green-100 dark:bg-green-900/40 text-green-800 dark:text-green-300",
  medium: "bg-yellow-100 dark:bg-yellow-900/40 text-yellow-800 dark:text-yellow-300",
  low: "bg-red-100 dark:bg-red-900/40 text-red-800 dark:text-red-300",
};

export function MessageBadges({ result }: MessageBadgesProps) {
  const intent = result.intent?.toLowerCase() ?? "unknown";
  const confidence = result.confidence?.toLowerCase() ?? "";
  const toolCount = result.used_tools?.length ?? 0;

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {/* Intent badge */}
      <span
        className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${
          intentColors[intent] ?? intentColors.unknown
        }`}
      >
        {intent.toUpperCase()}
      </span>

      {/* Confidence badge */}
      {confidence && (
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${
            confidenceColors[confidence] ?? "bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400"
          }`}
        >
          {confidence.charAt(0).toUpperCase() + confidence.slice(1)}
        </span>
      )}

      {/* Tool count */}
      {toolCount > 0 && (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400">
          {toolCount} tool{toolCount !== 1 ? "s" : ""}
        </span>
      )}

      {/* Step count */}
      {result.step_count > 0 && (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400">
          {result.step_count} step{result.step_count !== 1 ? "s" : ""}
        </span>
      )}
    </div>
  );
}
