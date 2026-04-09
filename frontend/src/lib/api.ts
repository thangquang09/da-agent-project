import type {
  QueryResponse,
  ThreadInfo,
  ConversationTurn,
  HealthResponse,
  TraceData,
  TurnArtifact,
  UploadResponse,
  TablesResponse,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, init);
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

// ─── Health ────────────────────────────────────────────────────────────────

export async function healthCheck(): Promise<boolean> {
  try {
    await fetchJSON<HealthResponse>("/health");
    return true;
  } catch {
    return false;
  }
}

// ─── Threads ───────────────────────────────────────────────────────────────

export function listThreads(limit = 50): Promise<ThreadInfo[]> {
  return fetchJSON<ThreadInfo[]>(`/threads?limit=${limit}`);
}

export function getThread(threadId: string): Promise<ThreadInfo> {
  return fetchJSON<ThreadInfo>(`/threads/${threadId}`);
}

export function getThreadHistory(
  threadId: string,
  limit = 20
): Promise<ConversationTurn[]> {
  return fetchJSON<ConversationTurn[]>(
    `/threads/${threadId}/history?limit=${limit}`
  );
}

export function getThreadArtifacts(threadId: string): Promise<TurnArtifact[]> {
  return fetchJSON<TurnArtifact[]>(`/threads/${threadId}/artifacts`);
}

export async function deleteThread(threadId: string): Promise<void> {
  await fetch(`${API_URL}/threads/${threadId}`, { method: "DELETE" });
}

// ─── Query (non-streaming) ────────────────────────────────────────────────

export function postQuery(
  query: string,
  threadId: string,
  opts?: {
    userSemanticContext?: string;
    version?: string;
  }
): Promise<QueryResponse> {
  return fetchJSON<QueryResponse>("/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      thread_id: threadId,
      user_semantic_context: opts?.userSemanticContext ?? null,
      version: opts?.version ?? "v3",
    }),
  });
}

// ─── Query with file upload (multipart) ──────────────────────────────────

export async function postQueryWithFiles(
  query: string,
  threadId: string,
  files: { name: string; data: ArrayBuffer; context: string }[],
  opts?: { userSemanticContext?: string }
): Promise<QueryResponse> {
  const form = new FormData();
  form.append("query", query);
  form.append("thread_id", threadId);
  form.append("version", "v3");
  if (opts?.userSemanticContext) {
    form.append("user_semantic_context", opts.userSemanticContext);
  }

  const contextsMap: Record<string, string> = {};
  for (const f of files) {
    const blob = new Blob([f.data], { type: "text/csv" });
    form.append("files", blob, f.name);
    if (f.context) contextsMap[f.name] = f.context;
  }
  if (Object.keys(contextsMap).length > 0) {
    form.append("contexts_json", JSON.stringify(contextsMap));
  }

  return fetchJSON<QueryResponse>("/query/upload", {
    method: "POST",
    body: form,
  });
}

// ─── Traces ────────────────────────────────────────────────────────────────

export function getTrace(runId: string): Promise<TraceData> {
  return fetchJSON<TraceData>(`/traces/${runId}`);
}

// ─── Data Upload ────────────────────────────────────────────────────────────

export async function uploadFiles(
  files: { name: string; data: ArrayBuffer }[]
): Promise<UploadResponse> {
  const form = new FormData();
  for (const f of files) {
    const blob = new Blob([f.data], { type: "text/csv" });
    form.append("files", blob, f.name);
  }

  return fetchJSON<UploadResponse>("/data/upload", {
    method: "POST",
    body: form,
  });
}

export function getTables(): Promise<TablesResponse> {
  return fetchJSON<TablesResponse>("/data/tables");
}
