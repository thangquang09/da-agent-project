"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

type Theme = "light" | "dark" | "system";

interface ThemeStore {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  /** Resolved effective theme (after applying 'system' preference) */
  effectiveTheme: "light" | "dark";
  _syncSystem: () => void;
}

export const useThemeStore = create<ThemeStore>()(
  persist(
    (set, get) => ({
      theme: "system",
      effectiveTheme: "light",

      setTheme: (theme) => {
        const effective =
          theme === "system"
            ? window.matchMedia("(prefers-color-scheme: dark)").matches
              ? "dark"
              : "light"
            : theme;
        set({ theme, effectiveTheme: effective });
        applyTheme(effective);
      },

      _syncSystem: () => {
        const { theme } = get();
        if (theme !== "system") return;
        const effective = window.matchMedia("(prefers-color-scheme: dark)").matches
          ? "dark"
          : "light";
        set({ effectiveTheme: effective });
        applyTheme(effective);
      },
    }),
    {
      name: "da-agent-theme",
      partialize: (s) => ({ theme: s.theme }),
    }
  )
);

function applyTheme(effective: "light" | "dark") {
  if (effective === "dark") {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }
}
