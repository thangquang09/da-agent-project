import { create } from "zustand";
import type {
  Message,
  ThreadInfo,
  ArtifactContent,
  QueryResponse,
  UploadedFile,
  ReportSectionResponse,
  TurnArtifact,
  TableInfo,
  UploadStatus,
  AgentStatus,
} from "@/lib/types";
import {
  listThreads,
  getThreadHistory,
  getThreadArtifacts,
  deleteThread as deleteThreadAPI,
  uploadFiles as uploadFilesAPI,
  getTables as getTablesAPI,
  updateTableContext as updateTableContextAPI,
  dropTable as dropTableAPI,
  cancelQuery as cancelQueryAPI,
} from "@/lib/api";
import { streamQuery } from "@/lib/sse";
import { postQueryWithFiles } from "@/lib/api";

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function generateThreadId(): string {
  return crypto.randomUUID();
}

function now(): string {
  return new Date().toISOString();
}

function buildAssistantContent(result: QueryResponse): string {
  if (result.response_mode === "report" && result.report_markdown) {
    return "Đây là report của bạn. Bấm vào nút Report để xem bản trình bày đầy đủ.";
  }
  return result.answer;
}

interface ChatStore {
  // ── Threads ──────────────────────────────────────────────────────────
  threads: ThreadInfo[];
  activeThreadId: string | null;

  // ── Messages (current thread) ────────────────────────────────────────
  messages: Message[];

  // ── Artifact panel ───────────────────────────────────────────────────
  artifactOpen: boolean;
  artifactContent: ArtifactContent | null;

  // ── UI state ─────────────────────────────────────────────────────────
  isStreaming: boolean;
  agentStatus: AgentStatus | null;
  uploadedFiles: UploadedFile[];
  sidebarOpen: boolean;
  _sseCloseFn: (() => void) | null;

  // ── Data panel ───────────────────────────────────────────────────────
  dataPanelOpen: boolean;
  availableTables: TableInfo[];
  uploadStatus: UploadStatus;
  uploadError: string | null;

  // ── Current user (set from userStore) ────────────────────────────────
  /** Call setUser after login to wire user_id into all scoped operations. */
  userId: string | null;

  // ── Actions ──────────────────────────────────────────────────────────
  setUser: (userId: string | null) => void;

  fetchThreads: () => Promise<void>;
  createThread: () => string;
  selectThread: (id: string) => Promise<void>;
  deleteThread: (id: string) => Promise<void>;

  sendMessage: (query: string) => void;
  sendMessageWithFiles: (query: string, files: UploadedFile[]) => Promise<void>;
  stopStreaming: () => void;

  openArtifact: (content: ArtifactContent) => void;
  closeArtifact: () => void;

  addFile: (file: UploadedFile) => void;
  removeFile: (id: string) => void;
  clearFiles: () => void;

  toggleSidebar: () => void;

  // ── Data panel actions ───────────────────────────────────────────────
  toggleDataPanel: () => void;
  fetchTables: () => Promise<void>;
  uploadFiles: (files: { name: string; data: ArrayBuffer; context?: string }[]) => Promise<void>;
  updateTableContext: (tableName: string, context: string) => Promise<void>;
  dropTable: (tableName: string) => Promise<void>;
}

export const useChatStore = create<ChatStore>((set, get) => ({
  // ── Initial state ────────────────────────────────────────────────────
  threads: [],
  activeThreadId: null,
  messages: [],
  artifactOpen: false,
  artifactContent: null,
  isStreaming: false,
  agentStatus: null,
  uploadedFiles: [],
  _sseCloseFn: null,
  sidebarOpen: true,
  dataPanelOpen: false,
  availableTables: [],
  uploadStatus: "idle",
  uploadError: null,
  userId: null,

  // ── User ─────────────────────────────────────────────────────────────
  setUser: (userId) => {
    set({ userId });
    // Refresh tables scoped to this user
    if (userId) {
      void get().fetchTables();
    }
  },

  // ── Thread actions ───────────────────────────────────────────────────
  fetchThreads: async () => {
    const { userId } = get();
    try {
      const threads = await listThreads(50, userId ?? undefined);
      set({ threads });
    } catch {
      // silently fail — sidebar shows empty
    }
  },

  createThread: () => {
    const { userId } = get();
    const rawId = generateThreadId();
    const id = userId ? `${userId}__${rawId}` : rawId;
    set({ activeThreadId: id, messages: [], artifactOpen: false, artifactContent: null });
    return id;
  },

  selectThread: async (id: string) => {
    set({ activeThreadId: id, messages: [], artifactOpen: false, artifactContent: null });
    try {
      const turns = await getThreadHistory(id, 50);

      // Build messages with lightweight metadata from turn + last_action_json
      const messages: Message[] = turns.map((t) => {
        const msg: Message = {
          id: `turn-${t.turn_number}`,
          role: t.role as "user" | "assistant",
          content: t.content || t.result_summary || "",
          timestamp: t.timestamp,
          status: "done" as const,
        };

        if (t.role === "assistant") {
          const action = t.last_action_json ?? {};
          const runId = (action.run_id as string) ?? "";
          const generatedSql = t.sql_generated ?? (action.generated_sql as string) ?? "";

          if (runId || generatedSql) {
            msg.result = {
              run_id: runId,
              thread_id: id,
              answer: msg.content,
              report_markdown: null,
              report_sections: [],
              intent: t.intent ?? (action.intent as string) ?? "unknown",
              intent_reason: "",
              response_mode: (action.response_mode as string) ?? "answer",
              confidence: (action.confidence as string) ?? "medium",
              used_tools: [],
              generated_sql: generatedSql,
              evidence: [],
              error_categories: [],
              tool_history: [],
              errors: [],
              total_token_usage: null,
              total_cost_usd: null,
              context_type: "default",
              visualization: null,
              visualizations: [],
              rows: null,
              step_count: 0,
            };
          }
        }
        return msg;
      });

      // Fetch persisted artifacts (reports, charts) and merge into messages
      try {
        const artifacts = await getThreadArtifacts(id);
        if (artifacts.length > 0) {
          const byTurn = new Map<number, TurnArtifact[]>();
          for (const a of artifacts) {
            const list = byTurn.get(a.turn_number) ?? [];
            list.push(a);
            byTurn.set(a.turn_number, list);
          }

          for (const msg of messages) {
            if (msg.role !== "assistant") continue;
            const turnNum = parseInt(msg.id.replace("turn-", ""), 10);
            const turnArtifacts = byTurn.get(turnNum);
            if (!turnArtifacts?.length) continue;

            // Ensure msg.result exists
            if (!msg.result) {
              msg.result = {
                run_id: "", thread_id: id, answer: msg.content,
                report_markdown: null, report_sections: [],
                intent: "unknown", intent_reason: "",
                response_mode: "answer", confidence: "medium",
                used_tools: [], generated_sql: "", evidence: [],
                error_categories: [], tool_history: [], errors: [],
                total_token_usage: null, total_cost_usd: null,
                context_type: "default", visualization: null, visualizations: [],
                rows: null, step_count: 0,
              };
            }

            for (const a of turnArtifacts) {
              if (a.artifact_type === "report") {
                msg.result.response_mode = "report";
                msg.result.report_markdown = (a.payload.report_markdown as string) ?? null;
                msg.result.report_sections =
                  (a.payload.report_sections as ReportSectionResponse[]) ?? [];
              } else if (a.artifact_type === "chart") {
                const items = Array.isArray(a.payload.items)
                  ? (a.payload.items as import("@/lib/types").VisualizationResponse[])
                  : [];
                const visualizations = items.length > 0
                  ? items
                  : [
                      {
                        success: true,
                        image_url: (a.payload.image_url as string) ?? null,
                        image_format: (a.payload.image_format as string) ?? "png",
                        image_size_bytes: null,
                        execution_time_ms: (a.payload.execution_time_ms as number) ?? 0,
                        error: null,
                      },
                    ];
                msg.result.visualizations = visualizations.filter((viz) => !!viz?.image_url);
                msg.result.visualization = msg.result.visualizations.at(-1) ?? null;
              }
            }
          }
        }
      } catch {
        // Artifacts fetch failed — buttons won't show but messages still work
      }

      set({ messages });
    } catch {
      // thread may have no history yet
    }
  },

  deleteThread: async (id: string) => {
    await deleteThreadAPI(id);
    const { threads, activeThreadId } = get();
    const updated = threads.filter((t) => t.thread_id !== id);
    const changes: Partial<ChatStore> = { threads: updated };
    if (activeThreadId === id) {
      changes.activeThreadId = null;
      changes.messages = [];
      changes.artifactOpen = false;
      changes.artifactContent = null;
    }
    set(changes);
  },

  // ── Send message (SSE streaming) ─────────────────────────────────────
  sendMessage: (query: string) => {
    const { activeThreadId } = get();
    const threadId = activeThreadId ?? get().createThread();

    const userMsg: Message = {
      id: generateId(),
      role: "user",
      content: query,
      timestamp: now(),
    };

    const assistantMsg: Message = {
      id: generateId(),
      role: "assistant",
      content: "",
      timestamp: now(),
      status: "thinking",
    };

    set((s) => ({
      activeThreadId: threadId,
      messages: [...s.messages, userMsg, assistantMsg],
      isStreaming: true,
    }));

    const closeSSE = streamQuery(query, threadId, {
      onStarted: () => {
        // already showing "thinking"
      },
      onStatus: (status: AgentStatus) => {
        set({ agentStatus: status });
      },
      onToken: (token: string) => {
        set((s) => ({
          messages: s.messages.map((m) =>
            m.id === assistantMsg.id
              ? { ...m, content: m.content + token, status: "streaming" as const }
              : m
          ),
        }));
      },
      onResult: (result: QueryResponse) => {
        set((s) => ({
          messages: s.messages.map((m) =>
            m.id === assistantMsg.id
              ? {
                  ...m,
                  content: buildAssistantContent(result),
                  result,
                  status: "done" as const,
                }
              : m
          ),
          isStreaming: false,
          agentStatus: null,
          _sseCloseFn: null,
        }));
        get().fetchThreads();
      },
      onError: (error: string) => {
        set((s) => ({
          messages: s.messages.map((m) =>
            m.id === assistantMsg.id
              ? {
                  ...m,
                  content: `Error: ${error}`,
                  status: "failed" as const,
                }
              : m
          ),
          isStreaming: false,
          agentStatus: null,
          _sseCloseFn: null,
        }));
      },
    });
    set({ _sseCloseFn: closeSSE });
  },

  // ── Send with files (multipart POST, no SSE) ─────────────────────────
  sendMessageWithFiles: async (query: string, files: UploadedFile[]) => {
    const { activeThreadId } = get();
    const threadId = activeThreadId ?? get().createThread();

    const userMsg: Message = {
      id: generateId(),
      role: "user",
      content: `${query}\n\n📎 ${files.map((f) => f.name).join(", ")}`,
      timestamp: now(),
    };

    const assistantMsg: Message = {
      id: generateId(),
      role: "assistant",
      content: "",
      timestamp: now(),
      status: "thinking",
    };

    set((s) => ({
      activeThreadId: threadId,
      messages: [...s.messages, userMsg, assistantMsg],
      isStreaming: true,
      uploadedFiles: [],
    }));

    try {
      const result = await postQueryWithFiles(
        query,
        threadId,
        files.map((f) => ({ name: f.name, data: f.data, context: f.context }))
      );

      set((s) => ({
        messages: s.messages.map((m) =>
          m.id === assistantMsg.id
            ? {
                ...m,
                content: buildAssistantContent(result),
                result,
                status: "done" as const,
              }
            : m
        ),
        isStreaming: false,
      }));
      get().fetchThreads();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Upload failed";
      set((s) => ({
        messages: s.messages.map((m) =>
          m.id === assistantMsg.id
            ? { ...m, content: `Error: ${msg}`, status: "failed" as const }
            : m
        ),
        isStreaming: false,
      }));
    }
  },

  // ── Artifact panel ───────────────────────────────────────────────────
  openArtifact: (content: ArtifactContent) => {
    set({ artifactOpen: true, artifactContent: content });
  },

  // ── Stop streaming ──────────────────────────────────────────────────
  stopStreaming: async () => {
    const { activeThreadId, _sseCloseFn } = get();

    if (_sseCloseFn) {
      _sseCloseFn();
    }

    if (activeThreadId) {
      try {
        await cancelQueryAPI(activeThreadId);
      } catch {
        // Backend cancel is best-effort
      }
    }

    set((s) => {
      const msgs = s.messages.map((m) => {
        if (m.role === "assistant" && m.status !== "done" && m.status !== "failed") {
          return {
            ...m,
            content: m.content || "Đã dừng.",
            status: "done" as const,
          };
        }
        return m;
      });
      return {
        messages: msgs,
        isStreaming: false,
        agentStatus: null,
        _sseCloseFn: null,
      };
    });
  },

  closeArtifact: () => {
    set({ artifactOpen: false, artifactContent: null });
  },

  // ── File management ──────────────────────────────────────────────────
  addFile: (file: UploadedFile) => {
    set((s) => ({ uploadedFiles: [...s.uploadedFiles, file] }));
  },

  removeFile: (id: string) => {
    set((s) => ({ uploadedFiles: s.uploadedFiles.filter((f) => f.id !== id) }));
  },

  clearFiles: () => set({ uploadedFiles: [] }),

  // ── Sidebar ──────────────────────────────────────────────────────────
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),

  // ── Data panel ───────────────────────────────────────────────────────
  toggleDataPanel: () => set((s) => ({ dataPanelOpen: !s.dataPanelOpen })),

  fetchTables: async () => {
    const { userId } = get();
    try {
      const response = await getTablesAPI(userId ?? undefined);
      set({ availableTables: response.tables });
    } catch {
      // silently fail
    }
  },

  uploadFiles: async (files: { name: string; data: ArrayBuffer; context?: string }[]) => {
    const { userId } = get();
    set({ uploadStatus: "uploading", uploadError: null });

    try {
      const response = await uploadFilesAPI(files, userId ?? undefined);

      if (response.errors.length > 0) {
        set({
          uploadStatus: "error",
          uploadError: response.errors.map((e) => `${e.file}: ${e.error}`).join("; "),
        });
        return;
      }

      set({
        uploadStatus: "success",
        availableTables: response.tables,
        uploadError: null,
      });

      // Auto-refresh tables after upload
      get().fetchTables();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Upload failed";
      set({ uploadStatus: "error", uploadError: msg });
    }
  },

  updateTableContext: async (tableName: string, context: string) => {
    const { userId } = get();
    try {
      await updateTableContextAPI(tableName, context, userId ?? undefined);
      get().fetchTables();
    } catch {
      // silently fail
    }
  },

  dropTable: async (tableName: string) => {
    const { userId } = get();
    try {
      await dropTableAPI(tableName, userId ?? undefined);
      get().fetchTables();
    } catch {
      // silently fail
    }
  },
}));
