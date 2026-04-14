"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { X, ZoomIn, ZoomOut } from "lucide-react";

interface ImageViewerProps {
  src: string;
  alt?: string;
  onClose: () => void;
}

const MIN_SCALE = 0.5;
const MAX_SCALE = 5;
const ZOOM_STEP = 0.4;

export function ImageViewer({ src, alt, onClose }: ImageViewerProps) {
  const [scale, setScale] = useState(1);
  const [translate, setTranslate] = useState({ x: 0, y: 0 });
  const dragging = useRef(false);
  const last = useRef({ x: 0, y: 0 });

  const zoomIn = useCallback(() => setScale((s) => Math.min(s + ZOOM_STEP, MAX_SCALE)), []);
  const zoomOut = useCallback(() => {
    setScale((s) => Math.max(s - ZOOM_STEP, MIN_SCALE));
    if (scale - ZOOM_STEP <= 1) setTranslate({ x: 0, y: 0 });
  }, [scale]);

  const reset = useCallback(() => {
    setScale(1);
    setTranslate({ x: 0, y: 0 });
  }, []);

  // Close on Escape
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "+" || e.key === "=") zoomIn();
      if (e.key === "-") zoomOut();
      if (e.key === "0") reset();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose, zoomIn, zoomOut, reset]);

  // Block body scroll
  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, []);

  // Mouse wheel zoom
  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    setScale((s) => {
      const next = s - e.deltaY * 0.002;
      return Math.min(Math.max(next, MIN_SCALE), MAX_SCALE);
    });
  }, []);

  // Drag to pan (only when zoomed)
  const handlePointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (scale <= 1) return;
      dragging.current = true;
      last.current = { x: e.clientX, y: e.clientY };
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
    },
    [scale],
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!dragging.current) return;
      setTranslate((t) => ({
        x: t.x + e.clientX - last.current.x,
        y: t.y + e.clientY - last.current.y,
      }));
      last.current = { x: e.clientX, y: e.clientY };
    },
    [],
  );

  const handlePointerUp = useCallback(() => {
    dragging.current = false;
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      onWheel={handleWheel}
    >
      {/* Top-right controls */}
      <div className="absolute top-4 right-4 flex items-center gap-2 z-10">
        <button
          onClick={zoomOut}
          disabled={scale <= MIN_SCALE}
          className="rounded-lg bg-white/10 p-2 text-white/80 hover:bg-white/20 hover:text-white transition disabled:opacity-30 disabled:cursor-not-allowed"
          title="Zoom out (-)"
        >
          <ZoomOut size={20} />
        </button>
        <span className="min-w-[4rem] text-center text-xs text-white/60 font-mono">
          {Math.round(scale * 100)}%
        </span>
        <button
          onClick={zoomIn}
          disabled={scale >= MAX_SCALE}
          className="rounded-lg bg-white/10 p-2 text-white/80 hover:bg-white/20 hover:text-white transition disabled:opacity-30 disabled:cursor-not-allowed"
          title="Zoom in (+)"
        >
          <ZoomIn size={20} />
        </button>
        <div className="w-px h-6 bg-white/20 mx-1" />
        <button
          onClick={onClose}
          className="rounded-lg bg-white/10 p-2 text-white/80 hover:bg-white/20 hover:text-white transition"
          title="Close (Esc)"
        >
          <X size={20} />
        </button>
      </div>

      {/* Bottom hint */}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-xs text-white/40 pointer-events-none">
        Scroll to zoom &middot; Drag to pan &middot; Esc to close
      </div>

      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={alt ?? "Chart preview"}
        className="max-h-[90vh] max-w-[90vw] object-contain select-none transition-transform duration-150"
        style={{
          transform: `translate(${translate.x}px, ${translate.y}px) scale(${scale})`,
          cursor: scale > 1 ? "grab" : "zoom-in",
        }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        draggable={false}
        onClick={() => {
          // Single click at scale=1 zooms to 2x
          if (scale === 1) {
            setScale(2);
          }
        }}
      />
    </div>
  );
}
