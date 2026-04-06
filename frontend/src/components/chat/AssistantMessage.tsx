"use client";

import type { Message } from "@/lib/types";
import { useChatStore } from "@/stores/chatStore";
import { MarkdownRenderer } from "@/components/shared/MarkdownRenderer";
import { LoadingDots } from "@/components/shared/LoadingDots";
import { MessageBadges } from "@/components/chat/MessageBadges";
import {
  Bot,
  FileText,
  Code2,
  BarChart3,
  Activity,
} from "lucide-react";

interface AssistantMessageProps {
  message: Message;
}

export function AssistantMessage({ message }: AssistantMessageProps) {
  const openArtifact = useChatStore((s) => s.openArtifact);
  const result = message.result;
  const isReportResponse = result?.response_mode === "report" && !!result?.report_markdown;

  const hasReport = !!result?.report_markdown;
  const hasSql = !!result?.generated_sql;
  const hasChart = !!result?.visualization?.image_data;
  const hasTrace = !!result?.run_id;
  const reportArtifactData = result?.report_markdown
    ? {
        markdown: result.report_markdown,
        sections: result.report_sections ?? [],
      }
    : null;

  return (
    <div className="flex justify-start">
      <div className="flex items-start gap-2.5 max-w-[85%]">
        <div className="w-7 h-7 rounded-full bg-emerald-50 dark:bg-emerald-950/50 flex items-center justify-center shrink-0 mt-1">
          <Bot size={15} className="text-emerald-600 dark:text-emerald-400" />
        </div>

        <div className="space-y-2">
          {/* Badges */}
          {result && message.status === "done" && (
            <MessageBadges result={result} />
          )}

          {/* Content */}
          <div className="bg-slate-50 dark:bg-slate-800 border border-slate-100 dark:border-slate-700 px-4 py-3 rounded-2xl rounded-tl-md">
            {message.status === "thinking" ? (
              <div className="flex items-center gap-2 text-sm text-slate-400">
                <LoadingDots />
                <span>Thinking&hellip;</span>
              </div>
            ) : message.status === "failed" ? (
              <p className="text-sm text-red-500">{message.content}</p>
            ) : (
              <div className={isReportResponse ? "space-y-3" : undefined}>
                <MarkdownRenderer content={message.content} />
                {isReportResponse && (
                  <button
                    onClick={() =>
                      openArtifact({
                        type: "report",
                        title: "Report",
                        data: reportArtifactData,
                        messageId: message.id,
                      })
                    }
                    className="inline-flex items-center gap-2 rounded-xl bg-slate-900 dark:bg-slate-700 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 dark:hover:bg-slate-600 transition-colors"
                  >
                    <FileText size={15} />
                    Mở Report
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Action buttons */}
          {message.status === "done" && result && (
            <div className="flex flex-wrap gap-1.5">
              {hasReport && (
                <ArtifactButton
                  icon={<FileText size={13} />}
                  label="Report"
                  onClick={() =>
                    openArtifact({
                      type: "report",
                      title: "Report",
                      data: reportArtifactData,
                      messageId: message.id,
                    })
                  }
                />
              )}
              {hasSql && (
                <ArtifactButton
                  icon={<Code2 size={13} />}
                  label="SQL"
                  onClick={() =>
                    openArtifact({
                      type: "sql",
                      title: "Generated SQL",
                      data: result.generated_sql,
                      messageId: message.id,
                    })
                  }
                />
              )}
              {hasChart && (
                <ArtifactButton
                  icon={<BarChart3 size={13} />}
                  label="Chart"
                  onClick={() =>
                    openArtifact({
                      type: "chart",
                      title: "Visualization",
                      data: result.visualization!.image_data,
                      messageId: message.id,
                    })
                  }
                />
              )}
              {hasTrace && (
                <ArtifactButton
                  icon={<Activity size={13} />}
                  label="Trace"
                  onClick={() =>
                    openArtifact({
                      type: "trace",
                      title: `Trace ${result.run_id.slice(0, 8)}`,
                      data: result.run_id,
                      messageId: message.id,
                    })
                  }
                />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ArtifactButton({
  icon,
  label,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 hover:border-slate-300 dark:hover:border-slate-600 transition-colors"
    >
      {icon}
      {label}
    </button>
  );
}
