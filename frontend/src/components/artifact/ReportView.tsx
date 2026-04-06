"use client";

import { MarkdownRenderer } from "@/components/shared/MarkdownRenderer";

interface ReportViewProps {
  markdown: string;
}

export function ReportView({ markdown }: ReportViewProps) {
  return (
    <article className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm">
      <MarkdownRenderer content={markdown} />
    </article>
  );
}
