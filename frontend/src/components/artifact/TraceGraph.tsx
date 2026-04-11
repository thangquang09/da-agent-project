"use client";

import { useCallback, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ChevronDown, ChevronRight, AlertCircle, Clock } from "lucide-react";

import type { TraceData } from "@/lib/types";
import {
  buildGraphLayout,
  observationTypeColor,
  type TraceNodeData,
  type GroupNodeData,
} from "@/lib/traceLayout";

// ─── Shared helpers ───────────────────────────────────────────────────────────

function formatMs(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function friendlyNodeName(name: string): string {
  return name
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// ─── Custom node: traceNode ────────────────────────────────────────────────────

function TraceNodeComponent({ data }: { data: TraceNodeData }) {
  const [expanded, setExpanded] = useState(false);

  const borderColor =
    data.status === "error" ? "#ef4444" : observationTypeColor(data.observationType);

  const bg = data.status === "error" ? "#fef2f2" : "#ffffff";

  const hasSummary =
    (data.inputSummary && Object.keys(data.inputSummary).length > 0) ||
    (data.outputSummary && Object.keys(data.outputSummary).length > 0);

  return (
    <div
      className="rounded-lg shadow-sm text-xs select-none"
      style={{
        background: bg,
        border: `1.5px solid ${borderColor}`,
        minWidth: 220,
      }}
    >
      <Handle
        type="target"
        position={Position.Top}
        style={{ background: borderColor, width: 8, height: 8 }}
      />

      {/* Header row */}
      <div
        className="flex items-center gap-1.5 px-3 py-2 cursor-pointer"
        onClick={() => hasSummary && setExpanded((e) => !e)}
      >
        {/* Observation type color dot */}
        <span
          className="inline-block rounded-full shrink-0"
          style={{ width: 8, height: 8, background: borderColor }}
        />

        {/* Node name */}
        <span
          className="font-medium flex-1 truncate text-slate-700"
          title={data.label}
        >
          {friendlyNodeName(data.label)}
        </span>

        {/* Retry badge */}
        {data.attempt > 1 && (
          <span className="text-[10px] px-1 rounded bg-amber-100 text-amber-700 shrink-0">
            ×{data.attempt}
          </span>
        )}

        {/* Error icon */}
        {data.status === "error" && (
          <AlertCircle size={12} className="text-red-500 shrink-0" />
        )}

        {/* Latency */}
        <span className="inline-flex items-center gap-0.5 text-slate-400 shrink-0">
          <Clock size={10} />
          {formatMs(data.latencyMs)}
        </span>

        {/* Expand chevron */}
        {hasSummary && (
          <span className="text-slate-400 shrink-0">
            {expanded ? (
              <ChevronDown size={12} />
            ) : (
              <ChevronRight size={12} />
            )}
          </span>
        )}
      </div>

      {/* Expanded detail panel */}
      {expanded && (
        <div className="border-t border-slate-100 px-3 py-2 space-y-2">
          {data.inputSummary &&
            Object.keys(data.inputSummary).length > 0 && (
              <SummaryBlock label="Input" data={data.inputSummary} />
            )}
          {data.outputSummary &&
            Object.keys(data.outputSummary).length > 0 && (
              <SummaryBlock label="Output" data={data.outputSummary} />
            )}
        </div>
      )}

      <Handle
        type="source"
        position={Position.Bottom}
        style={{ background: borderColor, width: 8, height: 8 }}
      />
    </div>
  );
}

function SummaryBlock({
  label,
  data,
}: {
  label: string;
  data: Record<string, unknown>;
}) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-0.5">
        {label}
      </p>
      <pre className="text-[10px] text-slate-600 bg-slate-50 rounded p-1.5 overflow-x-auto whitespace-pre-wrap break-words max-h-40">
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  );
}

// ─── Custom node: groupNode (subgraph container) ───────────────────────────────

function GroupNodeComponent({ data }: { data: GroupNodeData }) {
  return (
    <div
      className="rounded-xl h-full w-full"
      style={{
        background: "rgba(20, 184, 166, 0.06)",
        border: "1.5px dashed #14b8a6",
      }}
    >
      <span className="absolute -top-5 left-2 text-[10px] font-semibold text-teal-600 uppercase tracking-wide">
        {data.label}
      </span>
    </div>
  );
}

// ─── Custom node types registry ───────────────────────────────────────────────

const nodeTypes = {
  traceNode: TraceNodeComponent,
  groupNode: GroupNodeComponent,
} as const;

// ─── Run info bar ─────────────────────────────────────────────────────────────

function RunInfoBar({ run }: { run: TraceData["run"] }) {
  if (!run) return null;

  const intentColor: Record<string, string> = {
    sql: "bg-blue-50 text-blue-700",
    mixed: "bg-teal-50 text-teal-700",
    report: "bg-amber-50 text-amber-700",
    unknown: "bg-slate-50 text-slate-600",
  };
  const cls = intentColor[run.intent] ?? intentColor.unknown;

  return (
    <div className="flex flex-wrap items-center gap-2 px-3 py-2 bg-slate-50 border-b border-slate-100 text-xs">
      <span
        className={`px-2 py-0.5 rounded-full font-medium text-[11px] ${cls}`}
      >
        {run.intent}
      </span>
      <span className="text-slate-500 truncate max-w-[220px]" title={run.query}>
        {run.query}
      </span>
      <span className="ml-auto text-slate-400 shrink-0">
        {formatMs(run.latency_ms)}
      </span>
      {run.final_confidence && (
        <span className="text-slate-400 shrink-0">
          conf:{" "}
          <span
            className={
              run.final_confidence === "high"
                ? "text-green-600"
                : run.final_confidence === "low"
                ? "text-red-500"
                : "text-amber-600"
            }
          >
            {run.final_confidence}
          </span>
        </span>
      )}
    </div>
  );
}

// ─── Main TraceGraph component ────────────────────────────────────────────────

interface TraceGraphProps {
  trace: TraceData;
}

export function TraceGraph({ trace }: TraceGraphProps) {
  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => buildGraphLayout(trace.execution_flow ?? []),
    [trace]
  );

  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

  const onInit = useCallback(() => {}, []);

  if (initialNodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-40 text-sm text-slate-400">
        No execution nodes recorded
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <RunInfoBar run={trace.run} />
      <div className="flex-1 min-h-0" style={{ height: "calc(100% - 40px)" }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onInit={onInit}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          minZoom={0.3}
          maxZoom={2}
          attributionPosition="bottom-right"
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#e2e8f0" gap={20} />
          <Controls
            showInteractive={false}
            className="[&>button]:!rounded-md [&>button]:!border-slate-200"
          />
          <MiniMap
            nodeColor={(n) => {
              const data = n.data as TraceNodeData | GroupNodeData;
              if ("status" in data) {
                return data.status === "error"
                  ? "#ef4444"
                  : observationTypeColor(
                      (data as TraceNodeData).observationType
                    );
              }
              return "#14b8a6";
            }}
            maskColor="rgba(248,250,252,0.8)"
            className="!rounded-lg !border !border-slate-200"
          />
        </ReactFlow>
      </div>
    </div>
  );
}
