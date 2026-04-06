"use client";

import { useEffect } from "react";
import { useChatStore } from "@/stores/chatStore";
import { useThemeStore } from "@/stores/themeStore";
import {
  Plus,
  MessageSquare,
  Trash2,
  PanelLeftClose,
  Sun,
  Moon,
  Monitor,
} from "lucide-react";

export function Sidebar() {
  const threads = useChatStore((s) => s.threads);
  const activeThreadId = useChatStore((s) => s.activeThreadId);
  const fetchThreads = useChatStore((s) => s.fetchThreads);
  const createThread = useChatStore((s) => s.createThread);
  const selectThread = useChatStore((s) => s.selectThread);
  const deleteThread = useChatStore((s) => s.deleteThread);
  const toggleSidebar = useChatStore((s) => s.toggleSidebar);

  const theme = useThemeStore((s) => s.theme);
  const setTheme = useThemeStore((s) => s.setTheme);

  useEffect(() => {
    fetchThreads();
  }, [fetchThreads]);

  const cycleTheme = () => {
    const next = theme === "light" ? "dark" : theme === "dark" ? "system" : "light";
    setTheme(next);
  };

  const ThemeIcon =
    theme === "dark" ? Moon : theme === "light" ? Sun : Monitor;

  const themeLabel =
    theme === "dark" ? "Dark" : theme === "light" ? "Light" : "System";

  return (
    <aside className="flex flex-col w-[280px] min-w-[280px] h-full bg-slate-900 text-slate-200">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/50">
        <h1 className="text-base font-semibold tracking-tight">
          DA Agent Lab
        </h1>
        <button
          onClick={toggleSidebar}
          className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
          aria-label="Close sidebar"
        >
          <PanelLeftClose size={18} />
        </button>
      </div>

      {/* New Chat button */}
      <div className="px-3 py-3">
        <button
          onClick={createThread}
          className="flex items-center gap-2 w-full px-3 py-2.5 text-sm font-medium rounded-lg border border-slate-700 hover:bg-slate-800 transition-colors"
        >
          <Plus size={16} />
          New Chat
        </button>
      </div>

      {/* Thread list */}
      <nav className="flex-1 overflow-y-auto px-2 pb-4 space-y-0.5">
        {threads.length === 0 && (
          <p className="px-3 py-6 text-xs text-slate-500 text-center">
            No conversations yet
          </p>
        )}
        {threads.map((t) => {
          const isActive = t.thread_id === activeThreadId;
          return (
            <div
              key={t.thread_id}
              className={`group flex items-center gap-2 px-3 py-2.5 rounded-lg cursor-pointer transition-colors ${
                isActive
                  ? "bg-slate-700/60 text-white"
                  : "hover:bg-slate-800/60 text-slate-300"
              }`}
              onClick={() => selectThread(t.thread_id)}
            >
              <MessageSquare size={15} className="shrink-0 text-slate-400" />
              <div className="flex-1 min-w-0">
                <p className="text-sm truncate">
                  {t.summary || t.thread_id.slice(0, 12) + "..."}
                </p>
                {t.last_updated && (
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    {formatRelativeTime(t.last_updated)}
                  </p>
                )}
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  deleteThread(t.thread_id);
                }}
                className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-slate-600 text-slate-400 hover:text-red-400 transition-all"
                aria-label="Delete thread"
              >
                <Trash2 size={14} />
              </button>
            </div>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-3 py-3 border-t border-slate-700/50 flex items-center justify-between">
        <span className="text-[11px] text-slate-500">
          LangGraph v3 &middot; Hybrid Agent
        </span>
        <button
          onClick={cycleTheme}
          title={`Theme: ${themeLabel} (click to cycle)`}
          className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-[11px] text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-colors"
        >
          <ThemeIcon size={13} />
          <span>{themeLabel}</span>
        </button>
      </div>
    </aside>
  );
}

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
