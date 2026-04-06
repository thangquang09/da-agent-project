import type { QueryResponse } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

export interface StreamCallbacks {
  onStarted?: () => void;
  onResult?: (data: QueryResponse) => void;
  onError?: (error: string) => void;
  onClose?: () => void;
}

/**
 * Open an SSE connection to `GET /query/stream`.
 *
 * Backend sends NAMED SSE events:
 *   event: started  → data: {"event":"started","node":null,"data":{"query":"..."}}
 *   event: result   → data: {"event":"result","node":null,"data":{...QueryResponse}}
 *   event: error    → data: {"event":"error","node":null,"data":{"message":"...","category":"..."}}
 *
 * Returns a cleanup function that closes the EventSource.
 */
export function streamQuery(
  query: string,
  threadId: string,
  callbacks: StreamCallbacks,
  opts?: { userSemanticContext?: string }
): () => void {
  const params = new URLSearchParams({
    q: query,
    thread_id: threadId,
    version: "v3",
  });
  if (opts?.userSemanticContext) {
    params.set("user_semantic_context", opts.userSemanticContext);
  }

  const source = new EventSource(`${API_URL}/query/stream?${params}`);

  // Must use addEventListener for named events — onmessage only fires for
  // untyped events (no "event:" line in the SSE frame).
  source.addEventListener("started", () => {
    callbacks.onStarted?.();
  });

  source.addEventListener("result", (ev: MessageEvent) => {
    try {
      const payload = JSON.parse(ev.data) as {
        event: string;
        data: QueryResponse;
      };
      callbacks.onResult?.(payload.data);
    } catch {
      callbacks.onError?.("Failed to parse SSE result event");
    }
    source.close();
    callbacks.onClose?.();
  });

  source.addEventListener("error", (ev: MessageEvent) => {
    try {
      const payload = JSON.parse(ev.data) as {
        data: { message?: string; category?: string };
      };
      callbacks.onError?.(payload.data?.message ?? "Unknown error");
    } catch {
      // Also fires on connection failure (ev.data may be null)
      callbacks.onError?.("Connection lost");
    }
    source.close();
    callbacks.onClose?.();
  });

  return () => {
    source.close();
    callbacks.onClose?.();
  };
}
