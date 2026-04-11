"use client";

import { toBackendAssetUrl } from "@/lib/url";

interface ChartViewProps {
  imageUrl: string | null;
}

export function ChartView({ imageUrl }: ChartViewProps) {
  const resolvedImageUrl = toBackendAssetUrl(imageUrl);

  if (!resolvedImageUrl) {
    return (
      <div className="text-sm text-slate-400 dark:text-slate-500 text-center py-10">
        No chart data available
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm p-4">
      <img
        src={resolvedImageUrl}
        alt="Visualization"
        className="w-full h-auto rounded-lg"
      />
    </div>
  );
}
