"use client";

interface ChartViewProps {
  imageData: string; // base64-encoded PNG
}

export function ChartView({ imageData }: ChartViewProps) {
  if (!imageData) {
    return (
      <div className="text-sm text-slate-400 text-center py-10">
        No chart data available
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4">
      <img
        src={`data:image/png;base64,${imageData}`}
        alt="Visualization"
        className="w-full h-auto rounded-lg"
      />
    </div>
  );
}
