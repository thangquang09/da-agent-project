import type { QueryResponse, AgentStatus } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

interface StreamCallbacks {
  onStarted?: () => void;
  onStatus?: (status: AgentStatus) => void;
  onResult?: (data: QueryResponse) => void;
  onError?: (error: string) => void;
  onClose?: () => void;
}

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

  source.addEventListener("started", () => {
    callbacks.onStarted?.();
  });

  source.addEventListener("status", (ev: MessageEvent) => {
    try {
      const payload = JSON.parse(ev.data) as {
        event: string;
        node: string;
        data: AgentStatus;
      };
      callbacks.onStatus?.(payload.data);
    } catch {
      // malformed status event — ignore
    }
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
