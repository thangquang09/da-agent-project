"use client";

import type { Message } from "@/lib/types";
import { useChatStore } from "@/stores/chatStore";
import { MarkdownRenderer } from "@/components/shared/MarkdownRenderer";
import { MessageBadges } from "@/components/chat/MessageBadges";
import { AgentStatusIndicator } from "@/components/chat/AgentStatusIndicator";
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
  const agentStatus = useChatStore((s) => s.agentStatus);
  const result = message.result;
  const isReportResponse = result?.response_mode === "report" && !!result?.report_markdown;

  const hasReport = !!result?.report_markdown;
  const hasSql = !!result?.generated_sql;
  const hasChart = !!result?.visualization?.image_url;
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
        <div className="w-7 h-7 rounded-full bg-[#ece9e2] dark:bg-[#2b2b2b] flex items-center justify-center shrink-0 mt-1 border border-[#ddd9cf] dark:border-[#373737]">
          <Bot size={15} className="text-[#4b4b4b] dark:text-[#d1d1d1]" />
        </div>

        <div className="space-y-2">
          {/* Badges */}
          {result && message.status === "done" && (
            <MessageBadges result={result} />
          )}

          {/* Content */}
          <div className="bg-[#f6f4ef] dark:bg-[#1f1f1f] border border-[#e3e0d8] dark:border-[#303030] px-4 py-3 rounded-2xl rounded-tl-md">
            {message.status === "thinking" ? (
              <AgentStatusIndicator status={agentStatus} />
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
                    className="inline-flex items-center gap-2 rounded-xl bg-[#2f2f2f] dark:bg-[#e8e8e8] px-3 py-2 text-sm font-medium text-[#f7f7f7] dark:text-[#191919] hover:bg-[#3b3b3b] dark:hover:bg-[#d9d9d9] transition-colors"
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
                      data: result.visualization!.image_url,
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
      className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-[#ddd9cf] dark:border-[#353535] text-[#5b5b5b] dark:text-[#c9c9c9] hover:bg-[#ece9e2] dark:hover:bg-[#262626] hover:border-[#cfcac0] dark:hover:border-[#3d3d3d] transition-colors"
    >
      {icon}
      {label}
    </button>
  );
}
