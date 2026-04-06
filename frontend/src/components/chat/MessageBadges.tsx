"use client";

import type { QueryResponse } from "@/lib/types";

interface MessageBadgesProps {
  result: QueryResponse;
}

const intentColors: Record<string, string> = {
  sql: "bg-blue-100 text-blue-800",
  rag: "bg-purple-100 text-purple-800",
  mixed: "bg-amber-100 text-amber-800",
  unknown: "bg-slate-100 text-slate-600",
};

const confidenceColors: Record<string, string> = {
  high: "bg-green-100 text-green-800",
  medium: "bg-yellow-100 text-yellow-800",
  low: "bg-red-100 text-red-800",
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
            confidenceColors[confidence] ?? "bg-slate-100 text-slate-600"
          }`}
        >
          {confidence.charAt(0).toUpperCase() + confidence.slice(1)}
        </span>
      )}

      {/* Tool count */}
      {toolCount > 0 && (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-slate-100 text-slate-600">
          {toolCount} tool{toolCount !== 1 ? "s" : ""}
        </span>
      )}

      {/* Step count */}
      {result.step_count > 0 && (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-slate-100 text-slate-500">
          {result.step_count} step{result.step_count !== 1 ? "s" : ""}
        </span>
      )}
    </div>
  );
}
