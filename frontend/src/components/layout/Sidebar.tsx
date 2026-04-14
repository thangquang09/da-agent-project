"use client";

import { useEffect } from "react";
import { useChatStore } from "@/stores/chatStore";
import { useThemeStore } from "@/stores/themeStore";
import { useUserStore } from "@/stores/userStore";
import { beaconCleanup } from "@/lib/api";
import {
  Plus,
  MessageSquare,
  Trash2,
  PanelLeftClose,
  Sun,
  Moon,
  LogOut,
  User,
} from "lucide-react";

export function Sidebar() {
  const threads = useChatStore((s) => s.threads);
  const activeThreadId = useChatStore((s) => s.activeThreadId);
  const fetchThreads = useChatStore((s) => s.fetchThreads);
  const createThread = useChatStore((s) => s.createThread);
  const selectThread = useChatStore((s) => s.selectThread);
  const deleteThread = useChatStore((s) => s.deleteThread);
  const toggleSidebar = useChatStore((s) => s.toggleSidebar);
  const setUser = useChatStore((s) => s.setUser);

  const theme = useThemeStore((s) => s.theme);
  const effectiveTheme = useThemeStore((s) => s.effectiveTheme);
  const setTheme = useThemeStore((s) => s.setTheme);

  const email = useUserStore((s) => s.email);
  const userId = useUserStore((s) => s.userId);
  const logout = useUserStore((s) => s.logout);

  useEffect(() => {
    fetchThreads();
  }, [fetchThreads]);

  const handleLogout = () => {
    // Send cleanup beacon so backend drops user tables
    if (userId) beaconCleanup(userId);
    // Clear user from both stores
    logout();
    setUser(null);
  };

  const toggleTheme = () => {
    const current = theme === "system" ? effectiveTheme : theme;
    const next = current === "dark" ? "light" : "dark";
    setTheme(next);
  };

  const ThemeIcon = (theme === "system" ? effectiveTheme : theme) === "dark" ? Moon : Sun;

  const themeLabel = (theme === "system" ? effectiveTheme : theme) === "dark" ? "Dark" : "Light";

  return (
    <aside className="flex flex-col w-[280px] min-w-[280px] h-full bg-[#f7f6f3] dark:bg-[#1a1a1a] text-[#2f2f2f] dark:text-[#e8e8e8] border-r border-[#dfddd7] dark:border-[#2a2a2a]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#dfddd7] dark:border-[#2c2c2c]">
        <h1 className="text-base font-semibold tracking-tight">
          DA Agent Lab
        </h1>
        <button
          onClick={toggleSidebar}
          className="p-1.5 rounded-lg hover:bg-[#ece9e2] dark:hover:bg-[#252525] text-[#7a7a7a] dark:text-[#9d9d9d] hover:text-[#2f2f2f] dark:hover:text-[#e8e8e8] transition-colors"
          aria-label="Close sidebar"
        >
          <PanelLeftClose size={18} />
        </button>
      </div>

      {/* New Chat button */}
      <div className="px-3 py-3">
        <button
          onClick={createThread}
          className="flex items-center gap-2 w-full px-3 py-2.5 text-sm font-medium rounded-lg border border-[#d8d5ce] dark:border-[#363636] hover:bg-[#ece9e2] dark:hover:bg-[#252525] transition-colors"
        >
          <Plus size={16} />
          New Chat
        </button>
      </div>

      {/* Thread list */}
      <nav className="flex-1 overflow-y-auto px-2 pb-4 space-y-0.5">
        {threads.length === 0 && (
          <p className="px-3 py-6 text-xs text-[#8b8b8b] dark:text-[#9d9d9d] text-center">
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
                  ? "bg-[#eae7df] dark:bg-[#2b2b2b] text-[#1f1f1f] dark:text-white"
                  : "hover:bg-[#efede7] dark:hover:bg-[#252525] text-[#4d4d4d] dark:text-[#c8c8c8]"
              }`}
              onClick={() => selectThread(t.thread_id)}
            >
              <MessageSquare size={15} className="shrink-0 text-[#8b8b8b] dark:text-[#9f9f9f]" />
              <div className="flex-1 min-w-0">
                <p className="text-sm truncate">
                  {t.summary || t.thread_id.slice(0, 12) + "..."}
                </p>
                {t.last_updated && (
                  <p className="text-[11px] text-[#9a9a9a] dark:text-[#8c8c8c] mt-0.5">
                    {formatRelativeTime(t.last_updated)}
                  </p>
                )}
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  deleteThread(t.thread_id);
                }}
                className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-[#d8d4cc] dark:hover:bg-[#3a3a3a] text-[#8f8f8f] hover:text-red-500 transition-all"
                aria-label="Delete thread"
              >
                <Trash2 size={14} />
              </button>
            </div>
          );
        })}
      </nav>

      {/* User footer */}
      {email && (
        <div className="px-3 py-2.5 border-t border-[#dfddd7] dark:border-[#2c2c2c]">
          <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-[#edeae3] dark:bg-[#242424]">
            <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-100 dark:bg-blue-900/40">
              <User size={12} className="text-blue-600 dark:text-blue-400" />
            </div>
            <span className="flex-1 min-w-0 text-[11px] text-[#4d4d4d] dark:text-[#c0c0c0] truncate" title={email}>
              {email}
            </span>
            <button
              onClick={handleLogout}
              title="Đăng xuất"
              className="p-1 rounded hover:bg-red-100 dark:hover:bg-red-900/30 text-[#9a9a9a] hover:text-red-500 transition-colors"
            >
              <LogOut size={13} />
            </button>
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="px-3 py-3 border-t border-[#dfddd7] dark:border-[#2c2c2c] flex items-center justify-between">
        <span className="text-[11px] text-[#8f8f8f] dark:text-[#9a9a9a]">
          LangGraph v3 &middot; Hybrid Agent
        </span>
        <button
          onClick={toggleTheme}
          title={`Theme: ${themeLabel} (click to toggle)`}
          className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-[11px] text-[#767676] dark:text-[#a3a3a3] hover:bg-[#ece9e2] dark:hover:bg-[#252525] hover:text-[#2f2f2f] dark:hover:text-[#efefef] transition-colors"
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
