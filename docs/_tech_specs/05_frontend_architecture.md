# Frontend Architecture — DA Agent Lab

> **Source of truth**: `frontend/src/` — this doc must match the current code.

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Framework | Next.js | 16.2.2 |
| UI Library | React | 19.2.4 |
| Styling | Tailwind CSS | v4 |
| State Management | Zustand | 5.0.12 |
| Icons | Lucide React | 1.7.0 |
| Markdown | react-markdown + remark-gfm + rehype-highlight | 10.1.0 |
| Graph Viz | @xyflow/react (ReactFlow) | 12.10.2 |
| Language | TypeScript | 5.x |

---

## Directory Structure

```
frontend/src/
├── app/                        # Next.js App Router
│   ├── page.tsx                # Root page — assembles the three-panel layout
│   ├── layout.tsx              # Root layout — fonts, ThemeProvider, anti-FOUC
│   ├── globals.css             # Global styles, dark mode, report prose, animations
│   └── favicon.ico
├── components/
│   ├── artifact/               # Right panel artifact renderers
│   │   ├── ReportView.tsx      # Report document surface with section charts
│   │   ├── SqlView.tsx         # SQL code viewer with copy button
│   │   ├── ChartView.tsx       # Base64 image display
│   │   ├── TraceGraph.tsx      # ReactFlow interactive graph (custom nodes)
│   │   └── TraceTimeline.tsx   # Trace viewer — graph + timeline tabs
│   ├── chat/                   # Chat area components
│   │   ├── AgentStatusIndicator.tsx # Real-time agent status (spinner + Vietnamese label)
│   │   ├── AssistantMessage.tsx # Bot bubble + artifact action buttons
│   │   ├── ChatInput.tsx       # Text-only input (Enter to send, Shift+Enter newline)
│   │   ├── MessageBadges.tsx   # Intent / confidence / tool count badges
│   │   ├── MessageList.tsx     # Scrollable message container with auto-scroll
│   │   └── UserMessage.tsx     # User bubble
│   ├── data/                   # Data management panel
│   │   ├── DataUploadPanel.tsx # Container: file uploader + tables list
│   │   ├── FileUploader.tsx    # Drag-drop file upload with status indicators
│   │   └── TablesList.tsx      # Available tables (filters system tables)
│   ├── layout/                 # Top-level layout panels
│   │   ├── ArtifactPanel.tsx   # Resizable right panel (360–1200px)
│   │   ├── ChatPanel.tsx       # Center panel: header + messages + input
│   │   └── Sidebar.tsx         # Left sidebar: thread list + theme toggle
│   └── shared/                 # Reusable utilities
│       ├── LoadingDots.tsx     # Animated "thinking" dots
│       ├── MarkdownRenderer.tsx# react-markdown with GFM + syntax highlight
│       └── ThemeProvider.tsx   # Mounts once, applies persisted theme + system watch
├── hooks/
│   └── useTheme.ts             # Legacy theme hook (not used by current stores)
├── lib/
│   ├── api.ts                  # All backend API calls (REST)
│   ├── sse.ts                  # SSE streaming for query responses
│   ├── traceLayout.ts          # Maps TraceNode[] → ReactFlow nodes/edges
│   └── types.ts                # TypeScript interfaces mirroring backend models
└── stores/
    ├── chatStore.ts            # Primary state: threads, messages, artifacts, data panel
    └── themeStore.ts           # Theme state with localStorage persistence
```

---

## Page Layout

`page.tsx` renders a horizontal flex container with 4 conditional regions:

```
┌──────────────┬────────────────────┬──────────────┬─────────────────┐
│   Sidebar    │     ChatPanel      │  Data Panel  │  Artifact Panel │
│  (280px)     │     (flex-1)       │  (320px)     │  (480-560px)    │
│              │                    │  (toggle)    │  (resizable)    │
│  thread list │  header + messages │  upload +    │  report/sql/    │
│  new chat    │  + input           │  tables list │  chart/trace    │
│  theme cycle │                    │              │                 │
└──────────────┴────────────────────┴──────────────┴─────────────────┘
```

| Panel | Component | Width | Visibility |
|-------|-----------|-------|------------|
| Left sidebar | `Sidebar` | 280px fixed | `sidebarOpen` toggle |
| Center chat | `ChatPanel` | `flex-1` | Always visible |
| Data panel | `DataUploadPanel` | 320px fixed | `dataPanelOpen` toggle (button in ChatPanel header) |
| Right artifact | `ArtifactPanel` | 360–1200px resizable | `artifactOpen` toggle |

**Priority**: Data panel and Artifact panel occupy the same visual slot (right of chat). If both are open, Data panel renders first, then Artifact panel further right.

---

## State Management

### chatStore (Zustand) — `stores/chatStore.ts`

Single global store managing all application state:

#### State Slices

| Slice | Fields | Purpose |
|-------|--------|---------|
| Threads | `threads`, `activeThreadId` | Thread list from backend, active selection |
| Messages | `messages` | Current thread messages with `Message[]` |
| Artifact | `artifactOpen`, `artifactContent` | Right panel state |
| UI | `isStreaming`, `uploadedFiles`, `sidebarOpen` | Interaction state |
| Data | `dataPanelOpen`, `availableTables`, `uploadStatus`, `uploadError` | Data management panel |

#### Actions

| Action | Flow |
|--------|------|
| `fetchThreads()` | `GET /threads` → update `threads[]` |
| `createThread()` | Generate UUID → reset messages + artifact |
| `selectThread(id)` | `GET /threads/{id}/history` + `GET /threads/{id}/artifacts` → build `messages[]` |
| `deleteThread(id)` | `DELETE /threads/{id}` → remove from list |
| `sendMessage(query)` | Create user + assistant messages → `streamQuery()` SSE → update assistant on result |
| `sendMessageWithFiles()` | `POST /query/upload` (multipart) → update assistant on response |
| `openArtifact(content)` | Set `artifactOpen=true` + `artifactContent` |
| `closeArtifact()` | Reset artifact state |
| `toggleDataPanel()` | Toggle `dataPanelOpen` |
| `fetchTables()` | `GET /data/tables` → update `availableTables` |
| `uploadFiles(files)` | `POST /data/upload` → update `uploadStatus` + `availableTables` |

#### Message Lifecycle

```
sendMessage("query")
  1. Create user Message {role: "user", content: "query"}
  2. Create assistant Message {role: "assistant", content: "", status: "thinking"}
  3. Append both to messages[], set isStreaming=true
  4. Open SSE connection via streamQuery()
  5. On SSE "status" events → update agentStatus in store → AgentStatusIndicator shows label
  6. On SSE "result" event → update assistant message with content + result + status: "done", clear agentStatus
  7. On SSE "error" event → update assistant message with error + status: "failed", clear agentStatus
```

### themeStore (Zustand) — `stores/themeStore.ts`

- Persisted to `localStorage` key `da-agent-theme` (via `zustand/middleware/persist`)
- Themes: `"light"` | `"dark"` | `"system"`
- `effectiveTheme` resolves `"system"` to actual preference via `matchMedia`
- Anti-FOUC script in `layout.tsx` applies theme before first paint

---

## API Layer

### REST API — `lib/api.ts`

Base URL: `NEXT_PUBLIC_API_URL` env var (default: `http://localhost:8001`)

| Function | Endpoint | Method | Purpose |
|----------|----------|--------|---------|
| `healthCheck()` | `/health` | GET | Health check |
| `listThreads(limit)` | `/threads?limit=N` | GET | List conversation threads |
| `getThread(id)` | `/threads/{id}` | GET | Get thread metadata |
| `getThreadHistory(id, limit)` | `/threads/{id}/history?limit=N` | GET | Get conversation turns |
| `getThreadArtifacts(id)` | `/threads/{id}/artifacts` | GET | Get persisted report/chart artifacts |
| `deleteThread(id)` | `/threads/{id}` | DELETE | Delete thread |
| `postQuery(query, threadId)` | `/query` | POST | Non-streaming query |
| `postQueryWithFiles(query, threadId, files)` | `/query/upload` | POST | Multipart query with file attachments |
| `getTrace(runId)` | `/traces/{runId}` | GET | Get execution trace data |
| `uploadFiles(files)` | `/data/upload` | POST | Standalone file upload (CSV auto-register) |
| `getTables()` | `/data/tables` | GET | List all database tables |

### SSE Streaming — `lib/sse.ts`

Endpoint: `GET /query/stream?q=...&thread_id=...&version=v3`

| SSE Event | Trigger | Data |
|-----------|---------|------|
| `started` | Connection established | `{event, node, data: {query}}` |
| `status` | Node starts/completes during graph execution | `{event, node, data: AgentStatus}` |
| `result` | Graph execution complete | `{event, data: QueryResponse}` |
| `error` | Error during execution | `{event, data: {message, category}}` |

Uses `EventSource` with named event listeners (`addEventListener`). Auto-closes on result or error.

### Agent Status — Real-time Progress

When a query is in-flight, the backend emits `status` SSE events from every graph node via `StatusEmitter`. The flow:

1. `sse_service.py` creates a `StatusEmitter` with an `asyncio.Queue`
2. The emitter's callback is passed as `on_status` to `RunTracer`
3. Each `start_node()` / `end_node()` call pushes a `StatusEvent` to the queue
4. The SSE generator drains the queue and yields `event: status` frames
5. Frontend `sse.ts` handles `status` events → updates `chatStore.agentStatus`
6. `AgentStatusIndicator` component renders spinner + Vietnamese label

Node labels (defined in `backend/services/status_emitter.py`):

| Node | Started label | Completed label |
|------|--------------|-----------------|
| `task_grounder` | Đang phân tích câu hỏi... | Đã phân tích câu hỏi |
| `leader_agent` | Đang suy luận... | Đã suy luận xong |
| `profiler_sampler` | Đang lấy mẫu dữ liệu... | Đã lấy mẫu dữ liệu |
| `report_planner` | Đang lên kế hoạch báo cáo... | Đã lên kế hoạch báo cáo |
| `section_pipeline` | Đang viết mục báo cáo... | Đã viết mục báo cáo |
| `report_writer` | Đang tổng hợp báo cáo... | Đã tổng hợp báo cáo |
| `report_critic` | Đang kiểm chứng báo cáo... | Đã kiểm chứng báo cáo |
| ... | (see full list in `status_emitter.py`) | ... |

Fallback: If no status events arrive (e.g. non-SSE endpoints), `AgentStatusIndicator` shows a generic spinner + "Thinking..." label.

---

## Type System — `lib/types.ts`

All types mirror `backend/models/responses.py`:

| Type | Purpose |
|------|---------|
| `QueryResponse` | Full backend response (answer, SQL, report, viz, trace) |
| `VisualizationResponse` | Base64 chart image + metadata |
| `ReportSectionResponse` | Report section with insight + chart |
| `ThreadInfo` | Thread metadata (id, turn_count, summary, last_updated) |
| `ConversationTurn` | Single conversation turn from history |
| `Message` | Frontend message model (adds `status` and `result`) |
| `AgentStatus` | Real-time agent node status (node, phase, label, detail, timestamp) |
| `ArtifactContent` | Polymorphic artifact (type + data + messageId) |
| `UploadedFile` | Client-side file with ArrayBuffer data |
| `TraceData` / `TraceNode` | Execution trace from observability layer |
| `TableInfo` / `TableColumn` | Database table metadata |
| `UploadResponse` / `TablesResponse` | Data upload API responses |
| `UploadStatus` | Union: `"idle" \| "uploading" \| "success" \| "error"` |

### Artifact Types

```typescript
type ArtifactType = "report" | "sql" | "chart" | "trace"
```

Each type maps to a dedicated view component in `components/artifact/`.

---

## Component Details

### Artifact Panel — `ArtifactPanel.tsx`

- Resizable via left-edge drag handle (min 360px, max 1200px)
- Default widths per type: report=560, trace=600, sql=480, chart=480
- Resets width when artifact type changes
- Mouse drag implemented with `useRef` + `useEffect` event listeners (no library)

### Report View — `ReportView.tsx`

- Splits markdown into blocks by `##` headings via `splitReportMarkdown()`
- Matches report sections to headings by fuzzy key comparison via `matchSection()`
- Injects section charts inline under matching H2 blocks
- Unmatched charts rendered as "Additional Visualization" appendix
- Handles markdown wrapped in triple-backtick fences via `normalizeReportMarkdown()`

### Trace Graph — `TraceGraph.tsx` + `traceLayout.ts`

- Uses `@xyflow/react` (ReactFlow v12) for interactive DAG visualization
- `traceLayout.ts` maps `TraceNode[]` → ReactFlow `Node[]` + `Edge[]`:
  - Main chain: top-to-bottom, centered at x=300
  - Report subgraph nodes: grouped in dashed teal container
  - Parallel SQL task nodes: side-by-side at same Y
- Static topology encoded in `KNOWN_EDGES` array (filtered to nodes present in trace)
- Color scheme by `observation_type`: agent=blue, memory=purple, tool=amber, chain=teal
- Custom node types: `traceNode` (expandable detail) and `groupNode` (subgraph container)
- Trace timeline view: flat list with status icons, observation type, latency, attempt badges

### Data Panel — `data/`

- `DataUploadPanel`: container with header + FileUploader + TablesList
- `FileUploader`: drag-drop zone, accepts `.csv/.xlsx/.xls`, status indicators (idle → uploading → success/error)
- `TablesList`: fetches tables on mount, filters system tables (`result_store`, `conversation_turns`, `conversation_summaries`, `turn_artifacts`), shows column chips (max 5 visible)

### Chat Input — `ChatInput.tsx`

- Text-only input (no file upload since Data panel was added)
- Auto-growing textarea (max 200px)
- Enter to send, Shift+Enter for newline
- Disabled during streaming

### Assistant Message — `AssistantMessage.tsx`

- Renders badges (`MessageBadges`) when status is `"done"`
- Shows loading dots when status is `"thinking"`
- Conditionally renders "Mở Report" button for report-mode responses
- Action buttons: Report, SQL, Chart, Trace — each opens the corresponding artifact view
- Button visibility based on data availability (e.g., Trace button only if `run_id` exists)

### Conversation History Restoration — in `chatStore.selectThread()`

1. Fetch turns from `GET /threads/{id}/history`
2. Build `Message[]` from turns, extracting `last_action_json` for `run_id` and `generated_sql`
3. Fetch artifacts from `GET /threads/{id}/artifacts`
4. Merge persisted report/chart artifacts into assistant messages by `turn_number`
5. This ensures historical messages show the same artifact buttons as live ones

---

## Theme System

Two parallel implementations exist (legacy migration in progress):

1. **Current (active)**: `themeStore.ts` — Zustand store with `persist` middleware
   - Used by `Sidebar.tsx` and `ThemeProvider.tsx`
   - Persisted to `localStorage` key `da-agent-theme`

2. **Legacy**: `hooks/useTheme.ts` — standalone hook
   - Not imported by any current component
   - Can be removed

**Anti-FOUC**: `layout.tsx` includes an inline `<script>` that reads `da-agent-theme` from localStorage and applies `dark` class before first paint.

---

## CSS Architecture — `globals.css`

| Section | Purpose |
|---------|---------|
| Tailwind import | `@import "tailwindcss"` + highlight.js theme |
| CSS variables | `--sidebar-w`, `--artifact-w` |
| Dark mode | Body/background overrides |
| Scrollbar | Custom thin scrollbar (light + dark) |
| Prose tables | Styled markdown tables for chat messages |
| Report surfaces | Gradient backgrounds for report hero + body |
| Report prose | Typography overrides for report document (h1–h3, p, li, strong) |
| Thinking animation | Pulsing dots keyframe animation |
| Resize handle | Indigo gradient hover effect for ArtifactPanel drag |

---

## Environment Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | No | `http://localhost:8001` | Backend API base URL |

Configured in `frontend/.env.local`.

---

## Adding New Features — Checklist

1. **New artifact type**: Add to `ArtifactType` union in `types.ts` → add view in `components/artifact/` → add case in `ArtifactPanel.tsx` → add action button in `AssistantMessage.tsx`
2. **New API endpoint**: Add function in `lib/api.ts` → add types in `lib/types.ts` → add action in `chatStore.ts`
3. **New panel**: Create component → integrate in `page.tsx` → add toggle state in `chatStore.ts`
4. **New message decoration**: Add to `MessageBadges.tsx` or `AssistantMessage.tsx`
5. **New data component**: Add to `components/data/` → integrate in `DataUploadPanel.tsx`

---

## Known Limitations

- **No file upload in chat input**: Files must be uploaded via the Data panel. `sendMessageWithFiles` exists in store but no UI trigger.
- **SSE only for text queries**: File queries use multipart POST (no streaming).
- **Legacy `useTheme.ts` hook** still exists but is unused.
- **Data + Artifact panels overlap**: Both render simultaneously if both open, pushing content left.
- **System table filtering is frontend-only**: `TablesList` filters `SYSTEM_TABLES` set client-side.
