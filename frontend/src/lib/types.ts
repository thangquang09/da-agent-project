// Types mirroring backend/models/responses.py

export interface VisualizationResponse {
  success: boolean;
  image_data: string | null; // base64-encoded PNG
  image_format: string;
  execution_time_ms: number;
  error: string | null;
}

export interface ReportSectionResponse {
  section_id: string;
  title: string;
  insight_markdown: string;
  chart_image: VisualizationResponse | null;
  chart_manifest: Record<string, unknown> | null;
  limitations: string[];
}

export interface QueryResponse {
  run_id: string;
  thread_id: string;
  answer: string;
  report_markdown: string | null;
  report_sections: ReportSectionResponse[];
  intent: string;
  intent_reason: string;
  response_mode: string;
  confidence: string;
  used_tools: string[];
  generated_sql: string;
  evidence: string[];
  error_categories: string[];
  tool_history: Record<string, unknown>[];
  errors: Record<string, unknown>[];
  total_token_usage: number | null;
  total_cost_usd: number | null;
  context_type: string;
  visualization: VisualizationResponse | null;
  rows: number | null;
  context_chunks: number | null;
  step_count: number;
  // Fields returned by backend but not in Pydantic model (extra fields):
  sql_rows?: Record<string, unknown>[];
  sql_row_count?: number;
  result_metadata?: Record<string, unknown> | null;
}

export interface ThreadInfo {
  thread_id: string;
  turn_count: number;
  summary: string | null;
  last_updated: string | null;
  key_entities: string[];
}

export interface ConversationTurn {
  thread_id: string;
  turn_number: number;
  role: string;
  content: string;
  intent: string | null;
  sql_generated: string | null;
  result_summary: string | null;
  entities: string[];
  timestamp: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  graph_version: string;
}

// Frontend-only types

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  // Only on assistant messages:
  result?: QueryResponse;
  status?: "thinking" | "done" | "failed";
}

export type ArtifactType = "report" | "sql" | "chart" | "trace";

export interface ReportArtifactData {
  markdown: string;
  sections: ReportSectionResponse[];
}

export interface ArtifactContent {
  type: ArtifactType;
  title: string;
  data: unknown;
  messageId: string;
}

export interface UploadedFile {
  id: string;
  name: string;
  data: ArrayBuffer;
  context: string;
}

// SSE event shapes from GET /query/stream
export interface SSEEvent {
  event: "started" | "result" | "error";
  data: Record<string, unknown>;
}

// Trace data (from GET /traces/{run_id})
export interface TraceNode {
  node: string;
  status: string;
  latency_ms: number;
  observation_type: string;
  attempt: number;
  started_at: string;
  error_category?: string | null;
  input_summary?: Record<string, unknown> | null;
  output_summary?: Record<string, unknown> | null;
}

export interface TraceData {
  run_id: string;
  found: boolean;
  run: {
    run_id: string;
    thread_id: string;
    status: string;
    query: string;
    intent: string;
    latency_ms: number;
    total_steps: number;
    used_tools: string[];
    total_token_usage: number;
    total_cost_usd: number;
    final_confidence: string;
    started_at: string;
    ended_at: string;
  } | null;
  nodes: TraceNode[];
  execution_flow: TraceNode[];
  tool_calls: Record<string, unknown>[];
  stats: {
    total_nodes: number;
    error_nodes: number;
    total_latency_ms: number | null;
  };
}
