"use client";

import { useEffect } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { ChatPanel } from "@/components/layout/ChatPanel";
import { ArtifactPanel } from "@/components/layout/ArtifactPanel";
import { DataUploadPanel } from "@/components/data/DataUploadPanel";
import { LoginScreen } from "@/components/auth/LoginScreen";
import { WelcomeModal } from "@/components/onboarding/WelcomeModal";
import { useChatStore } from "@/stores/chatStore";
import { useUserStore } from "@/stores/userStore";
import { beaconCleanup } from "@/lib/api";

export default function Home() {
  const sidebarOpen = useChatStore((s) => s.sidebarOpen);
  const artifactOpen = useChatStore((s) => s.artifactOpen);
  const dataPanelOpen = useChatStore((s) => s.dataPanelOpen);
  const setUser = useChatStore((s) => s.setUser);

  const email = useUserStore((s) => s.email);
  const userId = useUserStore((s) => s.userId);
  const login = useUserStore((s) => s.login);

  // Sync userId into chatStore whenever it changes
  useEffect(() => {
    setUser(userId);
  }, [userId, setUser]);

  // Warn + cleanup on page unload (tab close / refresh)
  useEffect(() => {
    if (!userId) return;

    function handleBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
      // Modern browsers show a generic message; we send cleanup beacon
      beaconCleanup(userId!);
      // Return value triggers confirmation dialog (spec)
      return "";
    }

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [userId]);

  if (!email || !userId) {
    return <LoginScreen onLogin={login} />;
  }

  return (
    <div className="flex h-full bg-[var(--app-bg)] text-[var(--app-text)]">
      <WelcomeModal />

      {/* Left sidebar — thread list */}
      {sidebarOpen && <Sidebar />}

      {/* Center — chat area */}
      <ChatPanel />

      {/* Right — data management panel */}
      {dataPanelOpen && <DataUploadPanel />}

      {/* Right — artifact panel (report / SQL / chart / trace) */}
      {artifactOpen && <ArtifactPanel />}
    </div>
  );
}
