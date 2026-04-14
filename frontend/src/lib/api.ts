import type {
  QueryResponse,
  ThreadInfo,
  ConversationTurn,
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

export function getHealth(): Promise<{ status: string }> {
  return fetchJSON<{ status: string }>("/health");
}

// ─── Threads ───────────────────────────────────────────────────────────────

export function listThreads(limit = 50, userId?: string): Promise<ThreadInfo[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (userId) params.set("user_id", userId);
  return fetchJSON<ThreadInfo[]>(`/threads?${params.toString()}`);
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

// ─── Query with file upload (multipart) ──────────────────────────────────

export async function postQueryWithFiles(
  query: string,
  threadId: string,
  files: { name: string; data: ArrayBuffer; context: string }[],
  opts?: { userSemanticContext?: string; userId?: string }
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
  files: { name: string; data: ArrayBuffer; context?: string }[],
  userId?: string
): Promise<UploadResponse> {
  const form = new FormData();
  const contextsMap: Record<string, string> = {};
  for (const f of files) {
    const blob = new Blob([f.data], { type: "text/csv" });
    form.append("files", blob, f.name);
    if (f.context) contextsMap[f.name] = f.context;
  }
  if (Object.keys(contextsMap).length > 0) {
    form.append("contexts_json", JSON.stringify(contextsMap));
  }
  if (userId) {
    form.append("user_id", userId);
  }

  return fetchJSON<UploadResponse>("/data/upload", {
    method: "POST",
    body: form,
  });
}

export function getTables(userId?: string): Promise<TablesResponse> {
  const params = userId ? `?user_id=${encodeURIComponent(userId)}` : "";
  return fetchJSON<TablesResponse>(`/data/tables${params}`);
}

export async function updateTableContext(
  tableName: string,
  context: string,
  userId?: string
): Promise<{ table_name: string; business_context: string }> {
  return fetchJSON(`/data/tables/${encodeURIComponent(tableName)}/context`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ context, user_id: userId ?? "" }),
  });
}

export async function dropTable(
  tableName: string,
  userId?: string
): Promise<{ deleted: string }> {
  const params = userId ? `?user_id=${encodeURIComponent(userId)}` : "";
  return fetchJSON(`/data/tables/${encodeURIComponent(tableName)}${params}`, {
    method: "DELETE",
  });
}

// ─── User scoped operations ────────────────────────────────────────────────

export interface UserTablesResponse {
  user_id: string;
  tables: string[];
  count: number;
  limit: number;
  slots_remaining: number;
}

export interface UserCleanupResponse {
  user_id: string;
  dropped: string[];
  count: number;
  errors: string[];
}

export function getUserTables(userId: string): Promise<UserTablesResponse> {
  return fetchJSON<UserTablesResponse>(`/users/${encodeURIComponent(userId)}/tables`);
}

export async function cleanupUserTables(userId: string): Promise<UserCleanupResponse> {
  return fetchJSON<UserCleanupResponse>(
    `/users/${encodeURIComponent(userId)}/cleanup`,
    { method: "POST" }
  );
}

/** Fire-and-forget beacon for session end (logout / page unload). */
export function beaconCleanup(userId: string): void {
  if (typeof navigator === "undefined") return;
  const url = `${API_URL}/users/${encodeURIComponent(userId)}/cleanup`;
  // sendBeacon is text/plain; backend POST endpoint accepts it
  if (navigator.sendBeacon) {
    navigator.sendBeacon(url);
  } else {
    // Fallback: best-effort fetch (may not complete)
    void fetch(url, { method: "POST", keepalive: true }).catch(() => undefined);
  }
}

// ─── Cancel running query ──────────────────────────────────────────────────

export async function cancelQuery(
  threadId: string
): Promise<{ cancelled: boolean; thread_id: string }> {
  return fetchJSON("/query/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId }),
  });
}
