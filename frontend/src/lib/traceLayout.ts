/**
 * traceLayout.ts
 *
 * Maps TraceNode[] from the backend trace API into ReactFlow nodes and edges.
 *
 * Layout strategy:
 * - Main chain: top-to-bottom, centered at x=300
 * - Report subgraph nodes: grouped in a translucent container
 * - Parallel SQL task nodes (leader_sql_task_*): side-by-side at the same Y
 */

import type { Node, Edge } from "@xyflow/react";
import type { TraceNode } from "@/lib/types";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface TraceNodeData extends Record<string, unknown> {
  label: string;
  status: "ok" | "error";
  latencyMs: number;
  observationType: string;
  attempt: number;
  inputSummary?: Record<string, unknown> | null;
  outputSummary?: Record<string, unknown> | null;
}

export interface GroupNodeData extends Record<string, unknown> {
  label: string;
}

// ─── Static topology ──────────────────────────────────────────────────────────
// Encodes every possible directed edge from graph.py + report_subgraph.py.
// Only edges whose both endpoints appear in the actual trace will be emitted.

const KNOWN_EDGES: [string, string, string?][] = [
  ["process_uploaded_files", "inject_session_context"],
  ["inject_session_context", "task_grounder"],
  ["task_grounder", "leader_agent"],
  ["leader_agent", "artifact_evaluator"],
  // artifact_evaluator conditional edges
  ["artifact_evaluator", "leader_agent", "retry"],
  ["artifact_evaluator", "report_planner", "report"],
  ["artifact_evaluator", "capture_action_node", "finalize"],
  ["artifact_evaluator", "clarify_question_node", "clarify"],
  // report subgraph internal chain
  ["report_planner", "report_executor"],
  ["report_executor", "report_insight_generator"],
  ["report_insight_generator", "report_writer"],
  ["report_writer", "report_critic"],
  ["report_critic", "report_writer", "revise"],
  ["report_critic", "report_finalize", "approve"],
  ["report_finalize", "capture_action_node"],
  // parallel SQL
  ["leader_parallel_dispatch", "leader_parallel_aggregate"],
  // memory chain
  ["capture_action_node", "compact_and_save_memory"],
  ["clarify_question_node", "__end__"],
  ["compact_and_save_memory", "__end__"],
];

// ─── Group detection helpers ───────────────────────────────────────────────────

const REPORT_NODES = new Set([
  "report_planner",
  "report_executor",
  "report_insight_generator",
  "report_writer",
  "report_critic",
  "report_finalize",
]);

function isReportNode(name: string): boolean {
  return REPORT_NODES.has(name);
}

function isParallelTaskNode(name: string): boolean {
  return /^leader_sql_task_/.test(name);
}

// ─── Color scheme ─────────────────────────────────────────────────────────────

export function observationTypeColor(obs: string): string {
  switch (obs) {
    case "agent":
      return "#3b82f6"; // blue
    case "memory":
      return "#8b5cf6"; // purple
    case "tool":
      return "#f59e0b"; // amber
    case "chain":
      return "#14b8a6"; // teal
    default:
      return "#64748b"; // slate
  }
}

// ─── Layout engine ─────────────────────────────────────────────────────────────

const NODE_W = 220;
const NODE_H = 52;
const V_GAP = 24; // gap between rows
const H_GAP = 20; // gap between parallel nodes
const CENTER_X = 300;

export function buildGraphLayout(
  traceNodes: TraceNode[]
): { nodes: Node[]; edges: Edge[] } {
  if (traceNodes.length === 0) return { nodes: [], edges: [] };

  const nameSet = new Set(traceNodes.map((n) => n.node));
  const nodeMap = new Map(traceNodes.map((n) => [n.node, n]));

  // Separate parallel task nodes
  const parallelTaskNames = traceNodes
    .map((n) => n.node)
    .filter(isParallelTaskNode);

  // Determine render order: main chain interleaved with group anchors
  // We keep the original execution_flow order but cluster groups together.
  const mainChain: string[] = [];
  const seenGroups = { report: false, parallel: false };

  for (const tn of traceNodes) {
    const name = tn.node;
    if (isParallelTaskNode(name)) {
      if (!seenGroups.parallel) {
        seenGroups.parallel = true;
        mainChain.push("__parallel_group__");
      }
    } else if (isReportNode(name)) {
      if (!seenGroups.report) {
        seenGroups.report = true;
        mainChain.push("__report_group__");
      }
    } else {
      mainChain.push(name);
    }
  }

  const rfNodes: Node[] = [];
  const rfEdges: Edge[] = [];

  let y = 40;

  // Helper to push a single non-group node
  function pushNode(name: string, overrideY?: number): void {
    const tn = nodeMap.get(name);
    if (!tn) return;
    const posY = overrideY !== undefined ? overrideY : y;
    rfNodes.push({
      id: name,
      type: "traceNode",
      position: { x: CENTER_X - NODE_W / 2, y: posY },
      data: {
        label: name,
        status: tn.status === "error" ? "error" : "ok",
        latencyMs: tn.latency_ms,
        observationType: tn.observation_type,
        attempt: tn.attempt,
        inputSummary: tn.input_summary ?? null,
        outputSummary: tn.output_summary ?? null,
      } satisfies TraceNodeData,
      style: { width: NODE_W },
    });
  }

  for (const slot of mainChain) {
    if (slot === "__parallel_group__") {
      // Render all parallel task nodes side by side
      const count = parallelTaskNames.length;
      const totalWidth = count * NODE_W + (count - 1) * H_GAP;
      const startX = CENTER_X - totalWidth / 2;
      parallelTaskNames.forEach((name, i) => {
        const tn = nodeMap.get(name);
        if (!tn) return;
        rfNodes.push({
          id: name,
          type: "traceNode",
          position: { x: startX + i * (NODE_W + H_GAP), y },
          data: {
            label: name,
            status: tn.status === "error" ? "error" : "ok",
            latencyMs: tn.latency_ms,
            observationType: tn.observation_type,
            attempt: tn.attempt,
            inputSummary: tn.input_summary ?? null,
            outputSummary: tn.output_summary ?? null,
          } satisfies TraceNodeData,
          style: { width: NODE_W },
        });
      });
      y += NODE_H + V_GAP;
    } else if (slot === "__report_group__") {
      // Render group container + child nodes stacked inside
      const reportTraceNodes = traceNodes.filter((n) => isReportNode(n.node));
      const groupPadding = 20;
      const innerH =
        reportTraceNodes.length * (NODE_H + V_GAP) - V_GAP + groupPadding * 2;
      const groupW = NODE_W + groupPadding * 2;
      const groupX = CENTER_X - groupW / 2;

      rfNodes.push({
        id: "__report_group_container__",
        type: "groupNode",
        position: { x: groupX, y },
        data: { label: "Report Subgraph" } satisfies GroupNodeData,
        style: {
          width: groupW,
          height: innerH,
        },
      });

      let innerY = groupPadding;
      for (const rtn of reportTraceNodes) {
        rfNodes.push({
          id: rtn.node,
          type: "traceNode",
          position: { x: groupPadding, y: innerY },
          parentId: "__report_group_container__",
          extent: "parent",
          data: {
            label: rtn.node,
            status: rtn.status === "error" ? "error" : "ok",
            latencyMs: rtn.latency_ms,
            observationType: rtn.observation_type,
            attempt: rtn.attempt,
            inputSummary: rtn.input_summary ?? null,
            outputSummary: rtn.output_summary ?? null,
          } satisfies TraceNodeData,
          style: { width: NODE_W },
        });
        innerY += NODE_H + V_GAP;
      }

      y += innerH + V_GAP;
    } else {
      pushNode(slot);
      y += NODE_H + V_GAP;
    }
  }

  // ─── Edges ──────────────────────────────────────────────────────────────────
  let edgeIdx = 0;

  // Static topology edges (filtered to nodes in trace)
  for (const [src, tgt, label] of KNOWN_EDGES) {
    if (!nameSet.has(src) || !nameSet.has(tgt)) continue;
    const edgeId = `e-${src}-${tgt}-${edgeIdx++}`;
    rfEdges.push({
      id: edgeId,
      source: src,
      target: tgt,
      label: label ?? undefined,
      type: "smoothstep",
      animated: label === "retry" || label === "revise",
      style: {
        stroke:
          label === "retry" || label === "revise" ? "#f59e0b" : "#94a3b8",
        strokeWidth: 1.5,
      },
      labelStyle: {
        fontSize: 10,
        fill: "#94a3b8",
      },
      labelBgStyle: {
        fill: "#f8fafc",
        fillOpacity: 0.8,
      },
    });
  }

  // Parallel task nodes → connect dispatch → each task → aggregate
  if (parallelTaskNames.length > 0) {
    const dispatchInTrace = nameSet.has("leader_parallel_dispatch");
    const aggregateInTrace = nameSet.has("leader_parallel_aggregate");

    for (const taskName of parallelTaskNames) {
      if (dispatchInTrace) {
        rfEdges.push({
          id: `e-dispatch-${taskName}-${edgeIdx++}`,
          source: "leader_parallel_dispatch",
          target: taskName,
          type: "smoothstep",
          style: { stroke: "#94a3b8", strokeWidth: 1.5 },
        });
      }
      if (aggregateInTrace) {
        rfEdges.push({
          id: `e-${taskName}-aggregate-${edgeIdx++}`,
          source: taskName,
          target: "leader_parallel_aggregate",
          type: "smoothstep",
          style: { stroke: "#94a3b8", strokeWidth: 1.5 },
        });
      }
    }
  }

  return { nodes: rfNodes, edges: rfEdges };
}
