"use client";

import { MarkdownRenderer } from "@/components/shared/MarkdownRenderer";
import type { ReportArtifactData, ReportSectionResponse } from "@/lib/types";
import { FileText, Image as ImageIcon } from "lucide-react";

interface ReportViewProps {
  report: ReportArtifactData;
}

interface MarkdownBlock {
  heading: string | null;
  markdown: string;
}

function normalizeReportMarkdown(markdown: string): string {
  const trimmed = markdown.trim();
  const match = trimmed.match(/^```(?:markdown|md)?\s*([\s\S]*?)\s*```$/i);
  return match ? match[1].trim() : trimmed;
}

function normalizeKey(value: string): string {
  return value
    .toLowerCase()
    .replace(/[`*_#:.!-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function splitReportMarkdown(markdown: string): MarkdownBlock[] {
  const normalized = normalizeReportMarkdown(markdown);
  const lines = normalized.split("\n");
  const blocks: MarkdownBlock[] = [];
  let currentLines: string[] = [];
  let currentHeading: string | null = null;

  for (const line of lines) {
    const headingMatch = line.match(/^##\s+(.+)$/);
    if (headingMatch) {
      if (currentLines.length > 0) {
        blocks.push({
          heading: currentHeading,
          markdown: currentLines.join("\n").trim(),
        });
      }
      currentHeading = headingMatch[1].trim();
      currentLines = [line];
      continue;
    }
    currentLines.push(line);
  }

  if (currentLines.length > 0) {
    blocks.push({
      heading: currentHeading,
      markdown: currentLines.join("\n").trim(),
    });
  }

  return blocks.filter((block) => block.markdown.trim());
}

function matchSection(
  heading: string | null,
  sections: ReportSectionResponse[],
  usedIds: Set<string>,
): ReportSectionResponse | null {
  if (!heading) return null;
  const headingKey = normalizeKey(heading);
  for (const section of sections) {
    if (usedIds.has(section.section_id)) continue;
    const sectionKey = normalizeKey(section.title);
    if (!sectionKey) continue;
    if (headingKey.includes(sectionKey) || sectionKey.includes(headingKey)) {
      usedIds.add(section.section_id);
      return section;
    }
  }
  return null;
}

function ReportSectionChart({ section }: { section: ReportSectionResponse }) {
  const image = section.chart_image;
  if (!image?.image_data) return null;

  return (
    <figure className="mt-5 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center gap-2 border-b border-slate-200 bg-slate-50 px-4 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
        <ImageIcon size={14} />
        Visualization
      </div>
      <img
        src={`data:image/${image.image_format || "png"};base64,${image.image_data}`}
        alt={section.title || "Report visualization"}
        className="w-full h-auto bg-white"
      />
      {section.title && (
        <figcaption className="border-t border-slate-100 px-4 py-3 text-sm text-slate-500">
          {section.title}
        </figcaption>
      )}
    </figure>
  );
}

export function ReportView({ report }: ReportViewProps) {
  const blocks = splitReportMarkdown(report.markdown);
  const sections = report.sections ?? [];
  const usedSectionIds = new Set<string>();
  return (
    <article className="report-surface overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-[0_20px_60px_rgba(15,23,42,0.08)]">
      <div className="report-hero border-b border-slate-200 px-6 py-6">
        <div className="inline-flex items-center gap-2 rounded-full border border-sky-200 bg-white/80 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-sky-700">
          <FileText size={14} />
          Report
        </div>
        <p className="mt-4 max-w-xl text-sm leading-6 text-slate-600">
          Bản trình bày đầy đủ của báo cáo được render riêng khỏi khung chat để dễ đọc, rà soát và đối chiếu.
        </p>
      </div>

      <div className="px-6 py-8 md:px-8">
        <div className="space-y-8">
          {blocks.map((block, index) => {
            const matchedSection = matchSection(block.heading, sections, usedSectionIds);
            return (
              <section key={`${block.heading ?? "intro"}-${index}`}>
                <MarkdownRenderer content={block.markdown} className="report-prose" />
                {matchedSection && <ReportSectionChart section={matchedSection} />}
              </section>
            );
          })}

          {sections
            .filter((section) => !usedSectionIds.has(section.section_id))
            .map((section) => (
              <section key={section.section_id} className="rounded-2xl border border-dashed border-slate-200 bg-slate-50/70 p-4">
                <p className="mb-3 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                  Additional Visualization
                </p>
                <ReportSectionChart section={section} />
              </section>
            ))}
        </div>
      </div>
    </article>
  );
}
