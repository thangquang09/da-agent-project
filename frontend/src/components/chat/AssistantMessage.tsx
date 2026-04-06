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

  const hasReport = !!result?.report_markdown;
  const hasSql = !!result?.generated_sql;
  const hasChart = !!result?.visualization?.image_data;
  const hasTrace = !!result?.run_id;

  return (
    <div className="flex justify-start">
      <div className="flex items-start gap-2.5 max-w-[85%]">
        <div className="w-7 h-7 rounded-full bg-emerald-50 flex items-center justify-center shrink-0 mt-1">
          <Bot size={15} className="text-emerald-600" />
        </div>

        <div className="space-y-2">
          {/* Badges */}
          {result && message.status === "done" && (
            <MessageBadges result={result} />
          )}

          {/* Content */}
          <div className="bg-slate-50 border border-slate-100 px-4 py-3 rounded-2xl rounded-tl-md">
            {message.status === "thinking" ? (
              <div className="flex items-center gap-2 text-sm text-slate-400">
                <LoadingDots />
                <span>Thinking&hellip;</span>
              </div>
            ) : message.status === "failed" ? (
              <p className="text-sm text-red-500">{message.content}</p>
            ) : (
              <MarkdownRenderer content={message.content} />
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
                      data: result.report_markdown,
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
      className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-100 hover:border-slate-300 transition-colors"
    >
      {icon}
      {label}
    </button>
  );
}
