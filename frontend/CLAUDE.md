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

Three-panel layout (`src/app/page.tsx`):

| Panel | Component | Width |
|-------|-----------|-------|
| Left sidebar | `Sidebar` | 280px — thread history |
| Center chat | `ChatPanel` | flex — messages + input |
| Right artifact | `ArtifactPanel` | 480px default, 560px for report artifacts |

## State

Single Zustand store (`src/stores/chatStore.ts`) manages:
- Thread list, active thread, messages
- Artifact panel (open/close/content)
- File uploads, streaming state

## Report UX

- Report-mode assistant bubbles stay short and point users to the `Report` artifact instead of dumping the full document into chat.
- The right-side report panel renders the report as a document surface, not raw markdown.
- If backend returns `report_sections[].chart_image`, `ReportView` tries to inject section charts under matching H2 sections and falls back to an appendix-style block for unmatched charts.

## API

All backend calls in `src/lib/api.ts`. SSE streaming via `src/lib/sse.ts`.
Backend URL configured via `NEXT_PUBLIC_API_URL` env var (default: `http://localhost:8001`).
