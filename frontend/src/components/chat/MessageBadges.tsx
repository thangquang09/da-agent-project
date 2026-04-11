"use client";

import type { QueryResponse } from "@/lib/types";

interface MessageBadgesProps {
  result: QueryResponse;
}

const intentColors: Record<string, string> = {
  sql: "bg-[#ebe8e1] dark:bg-[#2a2a2a] text-[#3b3b3b] dark:text-[#d7d7d7]",
  rag: "bg-[#ebe8e1] dark:bg-[#2a2a2a] text-[#3b3b3b] dark:text-[#d7d7d7]",
  mixed: "bg-[#e8e5de] dark:bg-[#2a2a2a] text-[#3b3b3b] dark:text-[#d7d7d7]",
  unknown: "bg-[#ece9e2] dark:bg-[#2a2a2a] text-[#707070] dark:text-[#a5a5a5]",
};

const confidenceColors: Record<string, string> = {
  high: "bg-[#e7f0e6] dark:bg-[#223126] text-[#2e5b2e] dark:text-[#9fc89d]",
  medium: "bg-[#f3eddc] dark:bg-[#342d1f] text-[#746238] dark:text-[#d0b97c]",
  low: "bg-[#f6e5e5] dark:bg-[#3a2525] text-[#7a3b3b] dark:text-[#d9a3a3]",
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
            confidenceColors[confidence] ?? "bg-[#ece9e2] dark:bg-[#2a2a2a] text-[#707070] dark:text-[#a5a5a5]"
          }`}
        >
          {confidence.charAt(0).toUpperCase() + confidence.slice(1)}
        </span>
      )}

      {/* Tool count */}
      {toolCount > 0 && (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-[#ece9e2] dark:bg-[#2a2a2a] text-[#6a6a6a] dark:text-[#ababab]">
          {toolCount} tool{toolCount !== 1 ? "s" : ""}
        </span>
      )}

      {/* Step count */}
      {result.step_count > 0 && (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-[#ece9e2] dark:bg-[#2a2a2a] text-[#7a7a7a] dark:text-[#ababab]">
          {result.step_count} step{result.step_count !== 1 ? "s" : ""}
        </span>
      )}
    </div>
  );
}
