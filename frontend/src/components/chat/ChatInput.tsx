"use client";

import { useState, useRef, type KeyboardEvent } from "react";
import { useChatStore } from "@/stores/chatStore";
import { Send, Square } from "lucide-react";

export function ChatInput() {
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const isStreaming = useChatStore((s) => s.isStreaming);
  const sendMessage = useChatStore((s) => s.sendMessage);
  const stopStreaming = useChatStore((s) => s.stopStreaming);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || isStreaming) return;

    sendMessage(trimmed);
    setInput("");

    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleTextareaInput = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  };

  return (
    <div className="border-t border-[#dfddd7] dark:border-[#2b2b2b] bg-[#fcfcf9] dark:bg-[#141414] px-4 py-3">
      {/* Input row */}
      <div className="flex items-end gap-2 max-w-3xl mx-auto">
        {/* Textarea */}
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onInput={handleTextareaInput}
          onKeyDown={handleKeyDown}
          placeholder="Ask a data question..."
          rows={1}
          disabled={isStreaming}
          className="flex-1 resize-none rounded-xl border border-[#dcd8ce] dark:border-[#343434] bg-[#f7f5f0] dark:bg-[#1d1d1d] text-[#2f2f2f] dark:text-[#efefef] px-4 py-2.5 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-[#686868]/20 focus:border-[#8a8a8a] placeholder:text-[#8f8f8f] dark:placeholder:text-[#8b8b8b] disabled:opacity-50"
        />

        {/* Send / Stop button */}
        {isStreaming ? (
          <button
            onClick={stopStreaming}
            className="p-2.5 rounded-xl bg-red-500 hover:bg-red-600 text-white transition-colors"
            title="Dừng"
          >
            <Square size={16} />
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!input.trim()}
            className="p-2.5 rounded-xl bg-[#2f2f2f] hover:bg-[#3a3a3a] dark:bg-[#e9e9e9] dark:hover:bg-[#dcdcdc] text-[#fafafa] dark:text-[#171717] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <Send size={16} />
          </button>
        )}
      </div>
    </div>
  );
}
