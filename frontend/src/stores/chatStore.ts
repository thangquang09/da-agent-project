import { create } from "zustand";
import type {
  Message,
  ThreadInfo,
  ArtifactContent,
  QueryResponse,
  UploadedFile,
} from "@/lib/types";
import { listThreads, getThreadHistory, deleteThread as deleteThreadAPI } from "@/lib/api";
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
  uploadedFiles: UploadedFile[];
  sidebarOpen: boolean;

  // ── Actions ──────────────────────────────────────────────────────────
  fetchThreads: () => Promise<void>;
  createThread: () => string;
  selectThread: (id: string) => Promise<void>;
  deleteThread: (id: string) => Promise<void>;

  sendMessage: (query: string) => void;
  sendMessageWithFiles: (query: string, files: UploadedFile[]) => Promise<void>;

  openArtifact: (content: ArtifactContent) => void;
  closeArtifact: () => void;

  addFile: (file: UploadedFile) => void;
  removeFile: (id: string) => void;
  clearFiles: () => void;

  toggleSidebar: () => void;
}

export const useChatStore = create<ChatStore>((set, get) => ({
  // ── Initial state ────────────────────────────────────────────────────
  threads: [],
  activeThreadId: null,
  messages: [],
  artifactOpen: false,
  artifactContent: null,
  isStreaming: false,
  uploadedFiles: [],
  sidebarOpen: true,

  // ── Thread actions ───────────────────────────────────────────────────
  fetchThreads: async () => {
    try {
      const threads = await listThreads();
      set({ threads });
    } catch {
      // silently fail — sidebar shows empty
    }
  },

  createThread: () => {
    const id = generateThreadId();
    set({ activeThreadId: id, messages: [], artifactOpen: false, artifactContent: null });
    return id;
  },

  selectThread: async (id: string) => {
    set({ activeThreadId: id, messages: [], artifactOpen: false, artifactContent: null });
    try {
      const turns = await getThreadHistory(id, 50);
      const messages: Message[] = turns.map((t) => ({
        id: `turn-${t.turn_number}`,
        role: t.role as "user" | "assistant",
        content: t.content || t.result_summary || "",
        timestamp: t.timestamp,
        status: "done" as const,
      }));
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

    streamQuery(query, threadId, {
      onStarted: () => {
        // already showing "thinking"
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
        }));
        // Refresh thread list (new thread may have appeared)
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
        }));
      },
    });
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
}));
