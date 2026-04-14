"use client";

import { useState, useEffect, useRef } from "react";
import { Mail, ArrowRight, Loader2 } from "lucide-react";
import { getHealth } from "@/lib/api";

interface LoginScreenProps {
  onLogin: (email: string) => void;
}

function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
}

export function LoginScreen({ onLogin }: LoginScreenProps) {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [warming, setWarming] = useState<"idle" | "warming" | "ready">("warming");
  const inputRef = useRef<HTMLInputElement>(null);

  // Wake up backend on mount (cold-start warm-up)
  useEffect(() => {
    getHealth()
      .then(() => setWarming("ready"))
      .catch(() => setWarming("idle")); // non-fatal — user can still proceed
  }, []);

  // Autofocus input
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = email.trim();
    if (!trimmed) {
      setError("Vui lòng nhập email của bạn.");
      return;
    }
    if (!isValidEmail(trimmed)) {
      setError("Email không hợp lệ. Ví dụ: ten@example.com");
      return;
    }
    setError("");
    onLogin(trimmed);
  }

  return (
    <div className="flex h-full items-center justify-center bg-[var(--app-bg)] text-[var(--app-text)]">
      <div className="w-full max-w-sm px-6">
        {/* Logo / title */}
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[var(--sidebar-bg)] border border-[var(--border)] shadow-sm">
            <span className="text-2xl">📊</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">DA Agent Lab</h1>
          <p className="mt-1.5 text-sm text-[var(--text-secondary)]">
            Nhập email để bắt đầu phân tích dữ liệu
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="email"
              className="mb-1.5 block text-sm font-medium text-[var(--app-text)]"
            >
              Email
            </label>
            <div className="relative">
              <Mail
                size={16}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]"
              />
              <input
                ref={inputRef}
                id="email"
                type="email"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (error) setError("");
                }}
                placeholder="ten@example.com"
                autoComplete="email"
                className={`w-full rounded-lg border py-2.5 pl-9 pr-4 text-sm outline-none transition-colors
                  bg-[var(--input-bg,var(--sidebar-bg))]
                  placeholder:text-[var(--text-secondary)]
                  focus:ring-2 focus:ring-blue-500/40
                  ${error
                    ? "border-red-400 dark:border-red-500"
                    : "border-[var(--border)] focus:border-blue-400"
                  }`}
              />
            </div>
            {error && (
              <p className="mt-1.5 text-xs text-red-500 dark:text-red-400">{error}</p>
            )}
          </div>

          <button
            type="submit"
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-700 active:bg-blue-800 disabled:opacity-60"
          >
            Vào Chat
            <ArrowRight size={16} />
          </button>
        </form>

        {/* Backend warm-up status */}
        <div className="mt-5 flex items-center justify-center gap-1.5 text-xs text-[var(--text-secondary)]">
          {warming === "warming" && (
            <>
              <Loader2 size={12} className="animate-spin" />
              <span>Đang khởi động backend…</span>
            </>
          )}
          {warming === "ready" && (
            <>
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-green-500" />
              <span>Backend sẵn sàng</span>
            </>
          )}
          {warming === "idle" && (
            <span className="opacity-0 select-none">·</span>
          )}
        </div>

        <p className="mt-6 text-center text-[11px] text-[var(--text-secondary)] opacity-70">
          Không cần mật khẩu — email chỉ dùng để phân biệt session của bạn.
        </p>
      </div>
    </div>
  );
}
