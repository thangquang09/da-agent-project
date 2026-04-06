"use client";

import { useState } from "react";
import { Copy, Check } from "lucide-react";

interface SqlViewProps {
  sql: string;
}

export function SqlView({ sql }: SqlViewProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
        <span className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
          SQL
        </span>
        <button
          onClick={handleCopy}
          className="inline-flex items-center gap-1.5 px-2 py-1 text-xs text-slate-500 dark:text-slate-400 rounded-md hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors"
        >
          {copied ? (
            <>
              <Check size={12} className="text-green-500" />
              Copied
            </>
          ) : (
            <>
              <Copy size={12} />
              Copy
            </>
          )}
        </button>
      </div>

      {/* SQL code */}
      <pre className="p-4 overflow-x-auto text-sm leading-relaxed font-mono text-slate-800 dark:text-slate-200">
        <code>{sql}</code>
      </pre>
    </div>
  );
}
