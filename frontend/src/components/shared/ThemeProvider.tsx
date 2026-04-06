"use client";

import { useEffect } from "react";
import { useThemeStore } from "@/stores/themeStore";

/**
 * Mounts once at the top of the app.
 * Reads persisted theme from localStorage and applies it immediately,
 * then watches system preference changes when theme === "system".
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const setTheme = useThemeStore((s) => s.setTheme);
  const syncSystem = useThemeStore((s) => s._syncSystem);
  const theme = useThemeStore((s) => s.theme);

  // Apply persisted theme on first render
  useEffect(() => {
    setTheme(theme);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Watch system preference
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => syncSystem();
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [syncSystem]);

  return <>{children}</>;
}
