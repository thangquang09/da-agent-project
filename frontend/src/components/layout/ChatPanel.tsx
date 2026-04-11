"use client";

import { useChatStore } from "@/stores/chatStore";
import { MessageList } from "@/components/chat/MessageList";
import { ChatInput } from "@/components/chat/ChatInput";
import { PanelLeftOpen, PanelRightOpen, Database } from "lucide-react";

export function ChatPanel() {
  const sidebarOpen = useChatStore((s) => s.sidebarOpen);
  const toggleSidebar = useChatStore((s) => s.toggleSidebar);
  const dataPanelOpen = useChatStore((s) => s.dataPanelOpen);
  const toggleDataPanel = useChatStore((s) => s.toggleDataPanel);
  const messages = useChatStore((s) => s.messages);
  const activeThreadId = useChatStore((s) => s.activeThreadId);

  return (
    <div className="flex-1 flex flex-col min-w-0 h-full bg-[#fcfcf9] dark:bg-[#141414]">
      {/* Top bar */}
      <header className="flex items-center gap-3 px-4 py-2.5 border-b border-[#dfddd7] dark:border-[#2b2b2b] bg-[#fcfcf9]/90 dark:bg-[#141414]/90 backdrop-blur-sm">
        {!sidebarOpen && (
          <button
            onClick={toggleSidebar}
            className="p-1.5 rounded-lg hover:bg-[#ece9e2] dark:hover:bg-[#232323] text-[#7a7a7a] hover:text-[#2f2f2f] dark:text-[#a3a3a3] dark:hover:text-[#f0f0f0] transition-colors"
            aria-label="Open sidebar"
          >
            <PanelLeftOpen size={18} />
          </button>
        )}
        <h2 className="text-sm font-medium text-[#5f5f5f] dark:text-[#c3c3c3] flex-1">
          {activeThreadId
            ? `Thread ${activeThreadId.slice(0, 8)}...`
            : "DA Agent Lab"}
        </h2>
        {/* Data panel toggle */}
        <button
          onClick={toggleDataPanel}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg hover:bg-[#ece9e2] dark:hover:bg-[#232323] transition-colors ${
            dataPanelOpen
              ? "bg-[#e8e5de] dark:bg-[#2a2a2a] text-[#2f2f2f] dark:text-[#f0f0f0]"
              : "text-[#707070] dark:text-[#aaaaaa] hover:text-[#2f2f2f] dark:hover:text-[#f0f0f0]"
          }`}
          aria-label={dataPanelOpen ? "Close data panel" : "Open data panel"}
          title="Data Management"
        >
          <Database size={18} />
          <span className="text-sm font-medium">Data</span>
        </button>
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
      <div className="w-14 h-14 rounded-2xl bg-[#efede7] dark:bg-[#242424] flex items-center justify-center mb-5">
        <PanelRightOpen size={24} className="text-[#4e4e4e] dark:text-[#c7c7c7]" />
      </div>
      <h3 className="text-lg font-semibold text-[#2f2f2f] dark:text-[#f1f1f1] mb-2">
        DA Agent Lab
      </h3>
      <p className="text-sm text-[#6f6f6f] dark:text-[#ababab] max-w-md leading-relaxed">
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
            className="px-3.5 py-2 text-sm rounded-xl border border-[#dedad2] dark:border-[#323232] text-[#595959] dark:text-[#c6c6c6] hover:bg-[#efede7] dark:hover:bg-[#232323] hover:border-[#d2cec5] dark:hover:border-[#3d3d3d] transition-colors"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
