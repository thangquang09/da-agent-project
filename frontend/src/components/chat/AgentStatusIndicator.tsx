"use client";

import type { AgentStatus } from "@/lib/types";
import { Loader2 } from "lucide-react";

interface AgentStatusIndicatorProps {
  status: AgentStatus | null;
}

export function AgentStatusIndicator({ status }: AgentStatusIndicatorProps) {
  if (!status) {
    return <FallbackThinking />;
  }

  return (
    <div className="flex items-center gap-2.5 text-sm">
      <Loader2 size={14} className="animate-spin text-emerald-500 shrink-0" />
      <span className="text-slate-600 dark:text-slate-300 transition-all duration-300">
        {status.label}
      </span>
    </div>
  );
}

function FallbackThinking() {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-400">
      <Loader2 size={14} className="animate-spin" />
      <span>Thinking&hellip;</span>
    </div>
  );
}
