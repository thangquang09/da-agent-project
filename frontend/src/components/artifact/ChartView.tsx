"use client";

interface ChartViewProps {
  imageUrl: string | null;
}

export function ChartView({ imageUrl }: ChartViewProps) {
  if (!imageUrl) {
    return (
      <div className="text-sm text-slate-400 dark:text-slate-500 text-center py-10">
        No chart data available
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm p-4">
      <img
        src={imageUrl}
        alt="Visualization"
        className="w-full h-auto rounded-lg"
      />
    </div>
  );
}
