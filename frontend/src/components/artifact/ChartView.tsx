"use client";

import { useState } from "react";

import type { VisualizationResponse } from "@/lib/types";
import { toBackendAssetUrl } from "@/lib/url";

interface ChartViewProps {
  visualizations: VisualizationResponse[];
}

export function ChartView({ visualizations }: ChartViewProps) {
  const validVisualizations = visualizations.filter((viz) => !!viz?.image_url);
  const [activeIndex, setActiveIndex] = useState(0);
  const activeVisualization = validVisualizations[activeIndex] ?? null;
  const resolvedImageUrl = toBackendAssetUrl(activeVisualization?.image_url ?? null);

  if (!resolvedImageUrl || validVisualizations.length === 0) {
    return (
      <div className="text-sm text-slate-400 dark:text-slate-500 text-center py-10">
        No chart data available
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {validVisualizations.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {validVisualizations.map((_, index) => (
            <button
              key={index}
              onClick={() => setActiveIndex(index)}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                index === activeIndex
                  ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                  : "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200"
              }`}
            >
              {`Chart ${index + 1}`}
            </button>
          ))}
        </div>
      )}

      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm p-4">
        <img
          src={resolvedImageUrl}
          alt={`Visualization ${activeIndex + 1}`}
          className="w-full h-auto rounded-lg"
        />
      </div>
    </div>
  );
}
