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

  source.onmessage = (ev) => {
    try {
      const payload = JSON.parse(ev.data) as {
        event: string;
        data: Record<string, unknown>;
      };

      switch (payload.event) {
        case "started":
          callbacks.onStarted?.();
          break;
        case "result":
          callbacks.onResult?.(payload.data as unknown as QueryResponse);
          source.close();
          callbacks.onClose?.();
          break;
        case "error":
          callbacks.onError?.(
            (payload.data as { error?: string }).error ?? "Unknown error"
          );
          source.close();
          callbacks.onClose?.();
          break;
      }
    } catch {
      callbacks.onError?.("Failed to parse SSE event");
      source.close();
      callbacks.onClose?.();
    }
  };

  source.onerror = () => {
    callbacks.onError?.("Connection lost");
    source.close();
    callbacks.onClose?.();
  };

  return () => {
    source.close();
    callbacks.onClose?.();
  };
}
