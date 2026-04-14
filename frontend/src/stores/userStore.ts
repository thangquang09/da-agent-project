import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Convert an email address to a stable, URL-safe user_id.
 * We lowercase and replace non-alphanum chars with underscores.
 * Max 80 chars to match backend validation.
 */
export function emailToUserId(email: string): string {
  return email
    .toLowerCase()
    .replace(/@/g, "_at_")
    .replace(/[^a-z0-9_]/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "")
    .slice(0, 80);
}

interface UserStore {
  email: string | null;
  userId: string | null;
  /** Sign in with an email address — no password required. */
  login: (email: string) => void;
  /** Clear current session. */
  logout: () => void;
}

export const useUserStore = create<UserStore>()(
  persist(
    (set) => ({
      email: null,
      userId: null,

      login: (email: string) => {
        const userId = emailToUserId(email);
        set({ email, userId });
      },

      logout: () => {
        set({ email: null, userId: null });
      },
    }),
    {
      name: "da-agent-user",
      // Only persist email + userId — nothing else
      partialize: (s) => ({ email: s.email, userId: s.userId }),
    }
  )
);
