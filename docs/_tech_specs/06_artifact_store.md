# Artifact Store — File-Based Offload Architecture

> Source: `app/artifacts/`, `app/graph/state.py`, `backend/routers/artifacts.py`

## Problem

Heavy data (PNG chart images, full SQL result rows, report markdown) was stored **in-band** in LangGraph state as `bytes` / `base64` strings, then persisted to PostgreSQL JSONB. This caused:

- **Context bloat** — `WorkerArtifact.payload` carried full SQL results and base64 PNG strings through every graph node
- **Token waste** — LLM prompts included raw artifact data unnecessarily
- **DB bloat** — `agent.turn_artifacts.payload` stored multi-MB base64 strings in JSONB columns
- **Double encoding** — sandbox output was base64 → decoded to `bytes` → re-encoded to base64 for JSON

## Architecture

```
Sandbox (Docker/E2B)
  │  produces: VisualizationResult.image_data (bytes)
  │            ReportAnalysisResult.image_data (bytes)
  ▼
Graph Node (visualization_node, report_subgraph, etc.)
  │  saves bytes to filesystem via ArtifactFileStore
  │  puts URL path in state dict instead of bytes
  ▼
AgentState (LangGraph)
  │  visualization: {image_url: "/artifacts/thread/1/chart_abc.png", ...}
  │  WorkerArtifact: {artifact_path: "/artifacts/thread/1/chart_abc.png", metadata: {...}}
  │  ReportSection: {chart_image_url: "/artifacts/thread/1/section_2_def.png", ...}
  ▼
Backend (FastAPI)
  │  GET /artifacts/{path} → FileResponse (serves file from disk)
  │  QueryResponse: {visualization: {image_url: "/artifacts/...", ...}}
  │  TurnArtifact.payload: {image_url: "/artifacts/...", image_format: "png"}
  ▼
Frontend (Next.js)
  <img src="http://localhost:8001/artifacts/thread/1/chart_abc.png" />
```

## Key Principles

1. **File system is primary store** — All heavy data (PNG, SVG, CSV, markdown) saved under `ARTIFACT_ROOT/{thread_id}/{turn_number}/`
2. **LangGraph state is lightweight** — Only URLs/metadata, never bytes or base64
3. **PostgreSQL holds pointers** — `agent.turn_artifacts.payload` contains `image_url`, `image_format`, `image_size_bytes` — never binary
4. **Frontend fetches independently** — Images via `GET /artifacts/{path}`, not embedded in JSON

## Directory Convention

```
artifacts/
  {thread_id}/
    {turn_number}/
      chart_{uuid8}.png          # Standalone chart
      section_{id}_{uuid8}.png   # Report section chart
      report.md                  # Report markdown
      data_{uuid8}.csv            # Large SQL result data
```

## File Storage API (`app/artifacts/file_store.py`)

| Method | Purpose |
|--------|---------|
| `save_chart(thread_id, turn_number, image_data, image_format)` | Save PNG/SVG, return relative path |
| `save_report_markdown(thread_id, turn_number, markdown)` | Save `.md` file |
| `save_report_section_chart(thread_id, turn_number, section_id, image_data)` | Save section chart |
| `get_artifact_url(relative_path)` | Convert path → `/artifacts/{path}` URL |
| `resolve_path(relative_path)` | Convert path → absolute filesystem path |
| `delete_thread(thread_id)` | Remove all files for a thread |

## WorkerArtifact Changes

**Before:**
```python
class WorkerArtifact(TypedDict):
    artifact_type: Literal[...]
    status: Literal[...]
    payload: dict[str, Any]  # ← Heavy data embedded
    ...
```

**After:**
```python
class WorkerArtifact(TypedDict):
    artifact_type: Literal[...]
    status: Literal[...]
    artifact_path: str  # ← Relative path like "thread/1/chart_abc.png"
    metadata: dict[str, Any]  # ← Lightweight: {row_count, columns, image_format, ...}
    ...
```

## Visualization Dict Changes

**Before:**
```python
{"success": True, "image_data": b'\x89PNG...', "image_format": "png", ...}
```

**After:**
```python
{"success": True, "image_url": "/artifacts/thread/1/chart_abc.png",
 "image_format": "png", "image_size_bytes": 12345, ...}
```

## Report Section Changes

**Before:** `ReportSection.chart_image = {"image_data": bytes, "image_format": "png"}`
**After:** `ReportSection.chart_image_url = "thread/1/section_2_xyz.png"` + `chart_image_format = "png"`

## Helper Functions (`app/artifacts/helpers.py`)

| Function | Purpose |
|----------|---------|
| `build_viz_dict_from_result(result, thread_id, turn_number)` | Takes `VisualizationResult`, saves PNG, returns viz dict with `image_url` |
| `save_chart_to_file(image_data, ...)` | Save chart bytes, return relative path |
| `save_report_markdown_to_file(markdown, ...)` | Save report `.md` |
| `save_section_chart_to_file(image_data, section_id, ...)` | Save section chart |
| `read_chart_bytes(relative_path)` | Read bytes from file (for LLM multimodal input) |
| `chart_url_from_path(relative_path)` | Convert relative path → URL |

## API Endpoint

```
GET /artifacts/{file_path:path}
```

- Serves files from `ARTIFACT_ROOT` directory
- Path traversal protection (rejects `..` and leading `/`)
- Content-type detection from file extension
- Returns 404 for missing files

## Thread Lifecycle

- **Create**: Files saved automatically by graph nodes during query execution
- **Read**: Frontend fetches via `GET /artifacts/{path}`
- **History**: `GET /threads/{id}/artifacts` returns metadata + URLs from PostgreSQL
- **Delete**: `DELETE /threads/{id}` removes both PostgreSQL rows AND filesystem directory

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ARTIFACT_ROOT` | `./artifacts` | Root directory for artifact file storage |

## Migration Notes

- Old `image_data` (base64) payload fields in PostgreSQL are no longer written
- Frontend `VisualizationResponse.image_data` → `image_url`
- Frontend `ChartView` and `ReportView` components now use `<img src={url}>` instead of `<img src="data:image/png;base64,...">`
- `backend/utils.py:make_serializable()` still handles stray `bytes` values but no longer handles bulk base64 encoding of images
