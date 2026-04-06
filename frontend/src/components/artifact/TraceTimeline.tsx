"use client";

import { useEffect, useState } from "react";
import { getTrace } from "@/lib/api";
import type { TraceData, TraceNode } from "@/lib/types";
import { LoadingDots } from "@/components/shared/LoadingDots";
import { CheckCircle2, XCircle, Clock } from "lucide-react";

interface TraceTimelineProps {
  runId: string;
}

export function TraceTimeline({ runId }: TraceTimelineProps) {
  const [trace, setTrace] = useState<TraceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    getTrace(runId)
      .then((data) => {
        if (!cancelled) setTrace(data);
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : "Failed to load trace");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [runId]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-10 justify-center text-sm text-slate-400">
        <LoadingDots /> Loading trace...
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-sm text-red-500 text-center py-10">{error}</div>
    );
  }

  if (!trace || !trace.found) {
    return (
      <div className="text-sm text-slate-400 text-center py-10">
        Trace not found
      </div>
    );
  }

  const flow = trace.execution_flow ?? [];
  const stats = trace.stats;

  return (
    <div className="space-y-4">
      {/* Summary stats */}
      <div className="grid grid-cols-3 gap-3">
        <StatCard
          label="Nodes"
          value={String(stats.total_nodes)}
        />
        <StatCard
          label="Errors"
          value={String(stats.error_nodes)}
          danger={stats.error_nodes > 0}
        />
        <StatCard
          label="Latency"
          value={`${(stats.total_latency_ms / 1000).toFixed(1)}s`}
        />
      </div>

      {/* Timeline */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm divide-y divide-slate-100">
        {flow.map((node, i) => (
          <TraceRow key={`${node.node}-${i}`} node={node} />
        ))}
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  danger,
}: {
  label: string;
  value: string;
  danger?: boolean;
}) {
  return (
    <div className="bg-white rounded-lg border border-slate-200 p-3 text-center">
      <p className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">
        {label}
      </p>
      <p
        className={`text-lg font-semibold mt-0.5 ${
          danger ? "text-red-500" : "text-slate-800"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function TraceRow({ node }: { node: TraceNode }) {
  const isError = node.status === "error";

  return (
    <div className="flex items-center gap-3 px-4 py-2.5 text-sm">
      {/* Status icon */}
      {isError ? (
        <XCircle size={15} className="text-red-400 shrink-0" />
      ) : (
        <CheckCircle2 size={15} className="text-green-400 shrink-0" />
      )}

      {/* Node name */}
      <span className="font-medium text-slate-700 truncate flex-1">
        {node.node}
      </span>

      {/* Error category */}
      {node.error_category && (
        <span className="text-[11px] px-2 py-0.5 rounded-full bg-red-50 text-red-600">
          {node.error_category}
        </span>
      )}

      {/* Latency */}
      <span className="inline-flex items-center gap-1 text-xs text-slate-400 shrink-0">
        <Clock size={11} />
        {node.latency_ms < 1000
          ? `${node.latency_ms}ms`
          : `${(node.latency_ms / 1000).toFixed(1)}s`}
      </span>
    </div>
  );
}
