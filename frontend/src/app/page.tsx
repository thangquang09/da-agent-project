"use client";

import { Sidebar } from "@/components/layout/Sidebar";
import { ChatPanel } from "@/components/layout/ChatPanel";
import { ArtifactPanel } from "@/components/layout/ArtifactPanel";
import { DataUploadPanel } from "@/components/data/DataUploadPanel";
import { useChatStore } from "@/stores/chatStore";

export default function Home() {
  const sidebarOpen = useChatStore((s) => s.sidebarOpen);
  const artifactOpen = useChatStore((s) => s.artifactOpen);
  const dataPanelOpen = useChatStore((s) => s.dataPanelOpen);

  return (
    <div className="flex h-full">
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
