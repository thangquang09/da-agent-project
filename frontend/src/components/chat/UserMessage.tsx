"use client";

import type { Message } from "@/lib/types";
import { User } from "lucide-react";

interface UserMessageProps {
  message: Message;
}

export function UserMessage({ message }: UserMessageProps) {
  return (
    <div className="flex justify-end">
      <div className="flex items-start gap-2.5 max-w-[85%]">
        <div className="bg-[#2f2f2f] dark:bg-[#ededed] text-[#f8f8f8] dark:text-[#1a1a1a] px-4 py-2.5 rounded-2xl rounded-tr-md text-sm leading-relaxed">
          {message.content}
        </div>
        <div className="w-7 h-7 rounded-full bg-[#ece9e2] dark:bg-[#2b2b2b] flex items-center justify-center shrink-0 border border-[#ddd9cf] dark:border-[#373737]">
          <User size={14} className="text-[#535353] dark:text-[#cfcfcf]" />
        </div>
      </div>
    </div>
  );
}
