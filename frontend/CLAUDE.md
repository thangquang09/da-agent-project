# Frontend — DA Agent Lab

Next.js 16 + React 19 + Tailwind v4 + Zustand.

## Commands

```bash
npm run dev      # Dev server at localhost:3000
npm run build    # Production build
npm run start    # Serve production build
npm run lint     # ESLint
```

## Architecture

Four-panel layout (`src/app/page.tsx`):

| Panel | Component | Width |
|-------|-----------|-------|
| Left sidebar | `Sidebar` | 280px — thread history + theme toggle |
| Center chat | `ChatPanel` | flex — header + messages + input |
| Data panel | `DataUploadPanel` | 320px — file upload + tables list |
| Right artifact | `ArtifactPanel` | 360–1200px resizable — report/sql/chart/trace |

## State

Two Zustand stores:

- **`chatStore.ts`** — threads, messages, artifacts, data panel, streaming
- **`themeStore.ts`** — light/dark/system theme with localStorage persistence

## Key Flows

- **Query**: `sendMessage()` → SSE streaming via `lib/sse.ts` → update assistant message
- **History**: `selectThread()` → fetch turns + artifacts → reconstruct messages with artifact buttons
- **Data upload**: `uploadFiles()` → POST multipart → auto-refresh tables list
- **Artifact view**: `openArtifact()` → render in right panel (resizable)

## API

All backend calls in `src/lib/api.ts`. SSE streaming via `src/lib/sse.ts`.
Backend URL configured via `NEXT_PUBLIC_API_URL` env var (default: `http://localhost:8001`).

Artifact images returned from the backend may use relative `/artifacts/...` paths. Frontend image renderers must normalize these to the backend origin via `src/lib/url.ts` before passing them to `<img>`.

## Trace Rendering

- `TraceGraph` uses `buildGraphLayout()` from `src/lib/traceLayout.ts`
- Execution nodes must use unique React Flow IDs per occurrence, not raw `node.node` names, because report fan-out can emit repeated node names such as `section_pipeline_node`
- The graph keeps a best-effort static topology and adds sequential execution edges so repeated nodes still render deterministically

## Full Documentation

> **Detailed frontend architecture**: `docs/_tech_specs/05_frontend_architecture.md`

Covers: directory structure, component details, type system, CSS architecture, theme system, adding new features checklist, known limitations.
