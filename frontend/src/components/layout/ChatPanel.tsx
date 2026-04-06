"use client";

import { useChatStore } from "@/stores/chatStore";
import { MessageList } from "@/components/chat/MessageList";
import { ChatInput } from "@/components/chat/ChatInput";
import { PanelLeftOpen, PanelRightOpen } from "lucide-react";

export function ChatPanel() {
  const sidebarOpen = useChatStore((s) => s.sidebarOpen);
  const toggleSidebar = useChatStore((s) => s.toggleSidebar);
  const messages = useChatStore((s) => s.messages);
  const activeThreadId = useChatStore((s) => s.activeThreadId);

  return (
    <div className="flex-1 flex flex-col min-w-0 h-full bg-white">
      {/* Top bar */}
      <header className="flex items-center gap-3 px-4 py-2.5 border-b border-slate-200">
        {!sidebarOpen && (
          <button
            onClick={toggleSidebar}
            className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-500 hover:text-slate-700 transition-colors"
            aria-label="Open sidebar"
          >
            <PanelLeftOpen size={18} />
          </button>
        )}
        <h2 className="text-sm font-medium text-slate-600">
          {activeThreadId
            ? `Thread ${activeThreadId.slice(0, 8)}...`
            : "DA Agent Lab"}
        </h2>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        {messages.length === 0 ? (
          <EmptyState />
        ) : (
          <MessageList messages={messages} />
        )}
      </div>

      {/* Input */}
      <ChatInput />
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-8">
      <div className="w-14 h-14 rounded-2xl bg-indigo-50 flex items-center justify-center mb-5">
        <PanelRightOpen size={24} className="text-indigo-500" />
      </div>
      <h3 className="text-lg font-semibold text-slate-800 mb-2">
        DA Agent Lab
      </h3>
      <p className="text-sm text-slate-500 max-w-md leading-relaxed">
        Ask a data question in Vietnamese or English. The agent will query your
        database, retrieve context, generate visualizations, or write reports.
      </p>
      <div className="flex flex-wrap gap-2 mt-6 justify-center">
        {[
          "DAU 7 ngày gần đây?",
          "So sánh revenue Q1 vs Q2",
          "Retention D1 là gì?",
          "Vẽ biểu đồ doanh thu theo tháng",
        ].map((q) => (
          <button
            key={q}
            onClick={() => useChatStore.getState().sendMessage(q)}
            className="px-3.5 py-2 text-sm rounded-xl border border-slate-200 text-slate-600 hover:bg-slate-50 hover:border-slate-300 transition-colors"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
