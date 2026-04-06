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
        <div className="bg-indigo-500 text-white px-4 py-2.5 rounded-2xl rounded-tr-md text-sm leading-relaxed">
          {message.content}
        </div>
        <div className="w-7 h-7 rounded-full bg-indigo-100 flex items-center justify-center shrink-0">
          <User size={14} className="text-indigo-600" />
        </div>
      </div>
    </div>
  );
}
