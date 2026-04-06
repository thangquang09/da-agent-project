"use client";

import { useState, useRef, type KeyboardEvent } from "react";
import { useChatStore } from "@/stores/chatStore";
import { Send, Paperclip, X } from "lucide-react";

export function ChatInput() {
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const isStreaming = useChatStore((s) => s.isStreaming);
  const uploadedFiles = useChatStore((s) => s.uploadedFiles);
  const sendMessage = useChatStore((s) => s.sendMessage);
  const sendMessageWithFiles = useChatStore((s) => s.sendMessageWithFiles);
  const addFile = useChatStore((s) => s.addFile);
  const removeFile = useChatStore((s) => s.removeFile);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || isStreaming) return;

    if (uploadedFiles.length > 0) {
      sendMessageWithFiles(trimmed, uploadedFiles);
    } else {
      sendMessage(trimmed);
    }
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

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;

    Array.from(files).forEach((file) => {
      file.arrayBuffer().then((data) => {
        addFile({
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
          name: file.name,
          data,
          context: "",
        });
      });
    });

    // Reset input so same file can be re-selected
    e.target.value = "";
  };

  const handleTextareaInput = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  };

  return (
    <div className="border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-950 px-4 py-3">
      {/* Attached files */}
      {uploadedFiles.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2">
          {uploadedFiles.map((f) => (
            <span
              key={f.id}
              className="inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300"
            >
              📎 {f.name}
              <button
                onClick={() => removeFile(f.id)}
                className="p-0.5 rounded hover:bg-slate-200 dark:hover:bg-slate-700"
              >
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Input row */}
      <div className="flex items-end gap-2 max-w-3xl mx-auto">
        {/* File upload */}
        <label className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 cursor-pointer transition-colors">
          <Paperclip size={18} />
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            multiple
            className="hidden"
            onChange={handleFileChange}
          />
        </label>

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
          className="flex-1 resize-none rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 px-4 py-2.5 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 placeholder:text-slate-400 dark:placeholder:text-slate-500 disabled:opacity-50"
        />

        {/* Send button */}
        <button
          onClick={handleSend}
          disabled={!input.trim() || isStreaming}
          className="p-2.5 rounded-xl bg-indigo-500 hover:bg-indigo-600 dark:bg-indigo-600 dark:hover:bg-indigo-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <Send size={16} />
        </button>
      </div>
    </div>
  );
}
