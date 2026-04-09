"use client";

import { useCallback, useState } from "react";
import { useChatStore } from "@/stores/chatStore";
import { Upload, CheckCircle, AlertCircle, Loader2 } from "lucide-react";

export function FileUploader() {
  const [dragActive, setDragActive] = useState(false);
  const uploadStatus = useChatStore((s) => s.uploadStatus);
  const uploadError = useChatStore((s) => s.uploadError);
  const uploadFiles = useChatStore((s) => s.uploadFiles);

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  }, []);

  const processFiles = useCallback(
    async (files: FileList) => {
      const fileArray: { name: string; data: ArrayBuffer }[] = [];

      for (const file of Array.from(files)) {
        if (file.name.endsWith(".csv") || file.name.endsWith(".xlsx") || file.name.endsWith(".xls")) {
          const data = await file.arrayBuffer();
          fileArray.push({ name: file.name, data });
        }
      }

      if (fileArray.length > 0) {
        await uploadFiles(fileArray);
      }
    },
    [uploadFiles]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragActive(false);

      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        processFiles(e.dataTransfer.files);
      }
    },
    [processFiles]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files.length > 0) {
        processFiles(e.target.files);
      }
    },
    [processFiles]
  );

  const isUploading = uploadStatus === "uploading";

  return (
    <div className="space-y-3">
      <div
        className={`
          relative border-2 border-dashed rounded-xl p-6 transition-colors
          ${dragActive ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950/30" : "border-slate-300 dark:border-slate-700"}
          ${isUploading ? "opacity-60 pointer-events-none" : "hover:border-slate-400 dark:hover:border-slate-600"}
        `}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
      >
        <input
          type="file"
          accept=".csv,.xlsx,.xls"
          multiple
          onChange={handleChange}
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
          disabled={isUploading}
        />

        <div className="flex flex-col items-center gap-2 text-center">
          {isUploading ? (
            <>
              <Loader2 size={24} className="text-indigo-500 animate-spin" />
              <p className="text-sm text-slate-600 dark:text-slate-300">
                Processing files...
              </p>
            </>
          ) : (
            <>
              <Upload size={24} className="text-slate-400" />
              <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
                Drop CSV or Excel files here
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                or click to browse
              </p>
            </>
          )}
        </div>
      </div>

      {uploadStatus === "success" && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300">
          <CheckCircle size={16} />
          <span className="text-sm">Files uploaded successfully</span>
        </div>
      )}

      {uploadStatus === "error" && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-red-50 dark:bg-red-950/30 text-red-700 dark:text-red-300">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <div className="text-sm">
            <p className="font-medium">Upload failed</p>
            <p className="text-xs opacity-80">{uploadError}</p>
          </div>
        </div>
      )}
    </div>
  );
}