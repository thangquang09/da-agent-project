"use client";

import { useEffect, useState } from "react";
import {
  CheckCircle,
  XCircle,
  Clock,
  AlertCircle,
  Activity,
  List,
} from "lucide-react";

import { getTrace } from "@/lib/api";
import type { TraceData, TraceNode } from "@/lib/types";
import { TraceGraph } from "@/components/artifact/TraceGraph";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatMs(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function friendlyNodeName(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

const OBS_COLOR: Record<string, string> = {
  agent: "text-blue-600",
  memory: "text-purple-600",
  tool: "text-amber-600",
  chain: "text-teal-600",
};

// ─── Stats bar ────────────────────────────────────────────────────────────────

function StatsBar({ trace }: { trace: TraceData }) {
  const { stats } = trace;
  return (
    <div className="grid grid-cols-3 gap-2 px-3 py-2 bg-slate-50 border-b border-slate-100">
      <StatCard
        label="Nodes"
        value={String(stats.total_nodes)}
        icon={<Activity size={14} className="text-slate-400" />}
      />
      <StatCard
        label="Errors"
        value={String(stats.error_nodes)}
        highlight={stats.error_nodes > 0 ? "red" : undefined}
        icon={<AlertCircle size={14} className="text-slate-400" />}
      />
      <StatCard
        label="Latency"
        value={stats.total_latency_ms != null ? formatMs(stats.total_latency_ms) : "—"}
        icon={<Clock size={14} className="text-slate-400" />}
      />
    </div>
  );
}

function StatCard({
  label,
  value,
  icon,
  highlight,
}: {
  label: string;
  value: string;
  icon?: React.ReactNode;
  highlight?: "red" | "green";
}) {
  const valClass =
    highlight === "red"
      ? "text-red-600 font-semibold"
      : highlight === "green"
      ? "text-green-600 font-semibold"
      : "text-slate-700 font-semibold";
  return (
    <div className="rounded-md bg-white border border-slate-100 px-2 py-1.5 flex flex-col gap-0.5">
      <div className="flex items-center gap-1 text-slate-400 text-[10px]">
        {icon}
        <span className="uppercase tracking-wide">{label}</span>
      </div>
      <span className={`text-sm ${valClass}`}>{value}</span>
    </div>
  );
}

// ─── Timeline (flat list) ─────────────────────────────────────────────────────

function TimelineView({ nodes }: { nodes: TraceNode[] }) {
  if (nodes.length === 0) {
    return (
      <div className="py-10 text-center text-sm text-slate-400">
        No node records found
      </div>
    );
  }

  return (
    <div className="divide-y divide-slate-100">
      {nodes.map((node, i) => (
        <TimelineRow key={`${node.node}-${i}`} node={node} />
      ))}
    </div>
  );
}

function TimelineRow({ node }: { node: TraceNode }) {
  const isError = node.status === "error";
  const obsClass = OBS_COLOR[node.observation_type] ?? "text-slate-500";

  return (
    <div className={`px-3 py-2 flex items-center gap-2 text-xs ${isError ? "bg-red-50" : ""}`}>
      {isError ? (
        <XCircle size={14} className="text-red-500 shrink-0" />
      ) : (
        <CheckCircle size={14} className="text-green-500 shrink-0" />
      )}

      <div className="flex-1 min-w-0">
        <span className="font-medium text-slate-700 truncate block">
          {friendlyNodeName(node.node)}
        </span>
        <div className="flex items-center gap-1.5 mt-0.5">
          <span className={`text-[10px] ${obsClass}`}>
            {node.observation_type}
          </span>
          {node.attempt > 1 && (
            <span className="text-[10px] px-1 rounded bg-amber-100 text-amber-700">
              attempt {node.attempt}
            </span>
          )}
          {node.error_category && (
            <span className="text-[10px] px-1 rounded bg-red-100 text-red-700 truncate max-w-[100px]">
              {node.error_category}
            </span>
          )}
        </div>
      </div>

      <span className="text-slate-400 shrink-0 flex items-center gap-0.5">
        <Clock size={10} />
        {formatMs(node.latency_ms)}
      </span>
    </div>
  );
}

// ─── Tab bar ──────────────────────────────────────────────────────────────────

type Tab = "graph" | "timeline";

function TabBar({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
  return (
    <div className="flex border-b border-slate-100 bg-white">
      {(["graph", "timeline"] as Tab[]).map((t) => (
        <button
          key={t}
          onClick={() => onChange(t)}
          className={`flex items-center gap-1.5 px-4 py-2 text-xs font-medium transition-colors ${
            active === t
              ? "border-b-2 border-blue-500 text-blue-600"
              : "text-slate-500 hover:text-slate-700"
          }`}
        >
          {t === "graph" ? (
            <Activity size={12} />
          ) : (
            <List size={12} />
          )}
          {t.charAt(0).toUpperCase() + t.slice(1)}
        </button>
      ))}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

interface TraceTimelineProps {
  runId: string;
}

export function TraceTimeline({ runId }: TraceTimelineProps) {
  const [trace, setTrace] = useState<TraceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("graph");

  useEffect(() => {
    setLoading(true);
    setError(null);
    getTrace(runId)
      .then(setTrace)
      .catch(() => setError("Failed to load trace data"))
      .finally(() => setLoading(false));
  }, [runId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-32 text-sm text-slate-400">
        <div className="animate-spin rounded-full h-5 w-5 border-2 border-slate-200 border-t-blue-500 mr-2" />
        Loading trace…
      </div>
    );
  }

  if (error || !trace || !trace.found) {
    return (
      <div className="flex flex-col items-center justify-center h-32 gap-1 text-sm text-slate-400">
        <AlertCircle size={20} />
        <span>{error ?? "Trace not found"}</span>
      </div>
    );
  }

  const flowNodes = trace.execution_flow ?? [];

  return (
    <div className="flex flex-col h-full text-sm">
      <StatsBar trace={trace} />
      <TabBar active={tab} onChange={setTab} />

      <div className="flex-1 min-h-0 overflow-auto">
        {tab === "graph" ? (
          // Graph view needs a fixed height container for ReactFlow to render
          <div style={{ height: Math.max(500, flowNodes.length * 80) }}>
            <TraceGraph trace={trace} />
          </div>
        ) : (
          <TimelineView nodes={flowNodes} />
        )}
      </div>
    </div>
  );
}
