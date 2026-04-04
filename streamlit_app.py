from __future__ import annotations

import time
import uuid
from typing import Any

import streamlit as st

from app.logger import logger
from backend.http_client import get_trace, health_check, query_stream


st.set_page_config(page_title="DA Agent Lab", page_icon="📊", layout="wide")
st.title("DA Agent Lab")
st.caption("LangGraph DA Agent chat with trace visibility")


def run_agent(
    user_query: str,
    user_semantic_context: str | None = None,
    uploaded_files: list[str]
    | None = None,  # kept for API compat, unused (filenames go via data)
    uploaded_file_data: list[dict[str, Any]] | None = None,
    thread_id: str | None = None,
    version: str = "v2",
) -> dict:
    """
    Execute a query via the FastAPI backend using SSE streaming.

    Returns the same payload dict shape as the old direct run_query() call,
    so all downstream rendering code (_render_result, etc.) is unchanged.
    """
    effective_thread_id = thread_id or str(uuid.uuid4())
    logger.info(
        "streamlit.run_agent → backend thread={tid} query_len={qlen}",
        tid=effective_thread_id[:8],
        qlen=len(user_query),
    )

    result: dict[str, Any] = {}
    for event in query_stream(
        query=user_query,
        thread_id=effective_thread_id,
        user_semantic_context=user_semantic_context,
        uploaded_file_data=uploaded_file_data,
        version=version,
    ):
        event_type = event.get("event", "")
        if event_type == "result":
            result = event.get("data", {})
        elif event_type == "error":
            err_msg = event.get("data", {}).get("message", "Backend error")
            raise RuntimeError(err_msg)

    if not result:
        raise RuntimeError("Backend returned no result. Is the backend running?")

    logger.info(
        "streamlit.run_agent done run_id={run_id} intent={intent}",
        run_id=result.get("run_id", "unknown"),
        intent=result.get("intent", "unknown"),
    )
    return result


def _init_state() -> None:
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("pending_queries", [])
    st.session_state.setdefault("is_processing", False)
    st.session_state.setdefault("current_assistant_index", None)
    st.session_state.setdefault("user_semantic_context", "")
    st.session_state.setdefault("uploaded_csv_files", [])
    st.session_state.setdefault("csv_pairs", [])  # pair-based upload store
    st.session_state.setdefault("uploader_key", 0)  # increment to reset file widget
    # Session memory: thread_id persists for conversation memory
    st.session_state.setdefault("thread_id", str(uuid.uuid4()))
    st.session_state.setdefault("trace_cache", {})
    st.session_state.setdefault("health_cache", {"checked_at": 0.0, "ok": False})
    st.session_state.setdefault("graph_version", "v2")


def _get_backend_health(ttl_seconds: float = 10.0) -> bool:
    cache = st.session_state.get("health_cache", {})
    now = time.time()
    checked_at = float(cache.get("checked_at", 0.0) or 0.0)
    if now - checked_at >= ttl_seconds:
        ok = health_check()
        st.session_state["health_cache"] = {"checked_at": now, "ok": ok}
        return ok
    return bool(cache.get("ok", False))


def _get_cached_trace(run_id: str) -> dict[str, Any] | None:
    return st.session_state.get("trace_cache", {}).get(run_id)


def _refresh_trace(run_id: str) -> dict[str, Any] | None:
    trace_data = get_trace(run_id) if run_id else None
    trace_cache = st.session_state.setdefault("trace_cache", {})
    if run_id:
        trace_cache[run_id] = trace_data
    return trace_data


def _render_result(result: dict) -> None:
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Confidence", str(result.get("confidence", "unknown")).upper())
    col2.metric("Intent", str(result.get("intent", "unknown")).upper())
    col3.metric("Context Type", str(result.get("context_type", "default")).upper())
    col4.metric("Tools Used", len(result.get("used_tools", [])))
    col5.metric("Tokens", int(result.get("total_token_usage", 0) or 0))
    col6.metric("Cost (USD)", f"{float(result.get('total_cost_usd', 0) or 0):.6f}")

    st.write(result.get("answer", "No answer"))
    st.caption(f"Run ID: {result.get('run_id', '-')}")

    # Render visualization if present
    viz = result.get("visualization")
    if viz and viz.get("success") and viz.get("image_data"):
        st.subheader("📊 Visualization")
        try:
            import base64
            from PIL import Image
            import io

            image_data = viz["image_data"]
            # Handle both bytes and base64 string
            if isinstance(image_data, str):
                image_bytes = base64.b64decode(image_data)
            else:
                image_bytes = image_data

            image = Image.open(io.BytesIO(image_bytes))
            st.image(image, use_container_width=True)

            # Show visualization metadata
            with st.expander("Visualization Details", expanded=False):
                st.write(f"Format: {viz.get('image_format', 'png')}")
                st.write(f"Size: {len(image_bytes)} bytes")
                st.write(f"Execution time: {viz.get('execution_time_ms', 0):.0f}ms")
                if viz.get("error"):
                    st.error(f"Error: {viz['error']}")
        except Exception as e:
            st.error(f"Failed to render visualization: {e}")

    with st.expander("Agent Logs", expanded=False):
        tabs = st.tabs(["SQL", "Trace Timeline", "Trace Raw JSON", "Errors", "Raw"])
        with tabs[0]:
            st.code(result.get("generated_sql", ""), language="sql")

        run_id = result.get("run_id", "")
        trace_data = _get_cached_trace(run_id) if run_id else None
        trace_loaded = trace_data is not None
        trace_col1, trace_col2 = st.columns([1, 1])
        with trace_col1:
            if run_id and st.button(
                "Load Trace" if not trace_loaded else "Refresh Trace",
                key=f"trace_load_{run_id}",
                use_container_width=True,
            ):
                trace_data = _refresh_trace(run_id)
                trace_loaded = trace_data is not None
        with trace_col2:
            if run_id:
                st.caption(
                    "Trace cached"
                    if trace_loaded
                    else "Trace not loaded yet"
                )

        with tabs[1]:
            has_trace = trace_data and (
                trace_data.get("found")
                or trace_data.get("execution_flow")
                or trace_data.get("nodes")
            )

            if has_trace:
                run_info = trace_data.get("run", {})
                execution_flow = trace_data.get("execution_flow", [])
                stats = trace_data.get("stats", {})

                # Summary metrics
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Total Nodes", stats.get("total_nodes", 0))
                col2.metric("Errors", stats.get("error_nodes", 0))
                col3.metric(
                    "Total Latency", f"{stats.get('total_latency_ms', 0):.0f}ms"
                )
                col4.metric(
                    "Status",
                    "✅ Success"
                    if run_info.get("status") == "success"
                    else "❌ Failed",
                )

                st.divider()

                # Execution timeline
                st.subheader("📊 Execution Timeline")

                if execution_flow:
                    # Create a visual timeline
                    total_time = stats.get("total_latency_ms", 1)

                    for i, node in enumerate(execution_flow):
                        node_name = node.get("node", "unknown")
                        latency = node.get("latency_ms", 0)
                        status = node.get("status", "unknown")
                        obs_type = node.get("observation_type", "span")
                        error_cat = node.get("error_category")

                        # Calculate bar width percentage
                        width_pct = (
                            min(100, max(5, (latency / total_time) * 100))
                            if total_time > 0
                            else 10
                        )

                        # Status icon
                        status_icon = (
                            "✅"
                            if status == "ok"
                            else "❌"
                            if status == "error"
                            else "⏳"
                        )

                        # Observation type emoji
                        type_emoji = {
                            "classifier": "🔍",
                            "agent": "🤖",
                            "retriever": "📚",
                            "generation": "✨",
                            "tool": "🔧",
                            "guardrail": "🛡️",
                            "planner": "📋",
                            "aggregator": "🔀",
                            "chain": "⛓️",
                            "memory": "🧠",
                        }.get(obs_type, "📍")

                        # Create columns for the timeline row
                        cols = st.columns([2, 1, 6, 2])

                        with cols[0]:
                            st.write(f"{type_emoji} **{node_name}**")

                        with cols[1]:
                            st.write(f"{status_icon}")

                        with cols[2]:
                            # Visual bar representing latency
                            bar_color = (
                                "#28a745"
                                if status == "ok"
                                else "#dc3545"
                                if status == "error"
                                else "#ffc107"
                            )
                            st.markdown(
                                f"""
                                <div style="
                                    width: {width_pct}%; 
                                    height: 20px; 
                                    background-color: {bar_color}; 
                                    border-radius: 3px;
                                    display: flex;
                                    align-items: center;
                                    justify-content: flex-end;
                                    padding-right: 5px;
                                    font-size: 11px;
                                    color: white;
                                ">
                                    {latency:.1f}ms
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )

                        with cols[3]:
                            if error_cat:
                                st.caption(f"⚠️ {error_cat}")

                        st.caption(f"Attempt #{node.get('attempt', 1)}")
                else:
                    st.info("No execution flow data available")
            elif run_id:
                st.info("Click `Load Trace` to fetch execution details.")
            else:
                st.info("Trace data not found. Run ID: " + str(run_id))

        with tabs[2]:
            if trace_data:
                st.json(trace_data)
            elif run_id:
                st.info("Click `Load Trace` to fetch raw trace JSON.")
            else:
                st.info("Trace data not found. Run ID: " + str(run_id))

        with tabs[3]:
            st.json(result.get("errors", []))

        with tabs[4]:
            st.json(result)


def _append_user_query(query: str) -> None:
    normalized = query.strip()
    if not normalized:
        return
    st.session_state["chat_history"].append({"role": "user", "content": normalized})
    st.session_state["pending_queries"].append(normalized)
    logger.info(
        "streamlit.queue query enqueued queue_size={size}",
        size=len(st.session_state["pending_queries"]),
    )


def _render_sample_queries() -> None:
    st.subheader("Sample Queries")
    samples = [
        ("SQL", "DAU 7 ngày gần đây như thế nào?"),
        ("RAG", "Retention D1 là gì?"),
        ("Mixed", "Revenue tuần này giảm từ ngày nào và metric này tính ra sao?"),
    ]
    for label, query in samples:
        if st.button(
            f"{label}: {query}", key=f"sample_{label}", use_container_width=True
        ):
            _append_user_query(query)
            st.rerun()


def _schedule_next_if_needed() -> None:
    if st.session_state["is_processing"]:
        return
    if not st.session_state["pending_queries"]:
        return
    query = st.session_state["pending_queries"].pop(0)
    st.session_state["is_processing"] = True
    st.session_state["chat_history"].append(
        {
            "role": "assistant",
            "status": "thinking",
            "query": query,
            "content": "Agent đang phân tích câu hỏi...",
        }
    )
    st.session_state["current_assistant_index"] = (
        len(st.session_state["chat_history"]) - 1
    )
    logger.info(
        "streamlit.queue dequeued query, remaining={remaining}",
        remaining=len(st.session_state["pending_queries"]),
    )
    st.rerun()


def _run_current_query_if_needed() -> None:
    if not st.session_state["is_processing"]:
        return
    idx = st.session_state.get("current_assistant_index")
    if idx is None:
        st.session_state["is_processing"] = False
        return

    pending_item = st.session_state["chat_history"][idx]
    query = str(pending_item.get("query", "")).strip()
    if not query:
        st.session_state["is_processing"] = False
        st.session_state["current_assistant_index"] = None
        return

    user_ctx = st.session_state.get("user_semantic_context", "") or None
    # Build file data from pair-based store: each pair has name, data, context
    uploaded_file_data: list[dict[str, Any]] = [
        {"name": p["name"], "data": p["data"], "context": p.get("context", "")}
        for p in st.session_state.get("csv_pairs", [])
        if p.get("data")
    ]
    uploaded_filenames: list[str] = [p["name"] for p in uploaded_file_data]

    with st.chat_message("assistant"):
        with st.status("Thinking...", expanded=True) as status:
            st.write(f"Đang xử lý: `{query}`")
            st.write("Routing intent -> gọi tools -> tổng hợp kết quả")
            try:
                result = run_agent(
                    query,
                    user_semantic_context=user_ctx,
                    uploaded_files=uploaded_filenames if uploaded_filenames else None,
                    uploaded_file_data=uploaded_file_data
                    if uploaded_file_data
                    else None,
                    thread_id=st.session_state.get("thread_id"),
                    version=st.session_state.get("graph_version", "v2"),
                )
                pending_item["status"] = "done"
                pending_item["content"] = result.get("answer", "No answer")
                pending_item["result"] = result
                status.update(label="Completed", state="complete")
            except Exception as exc:  # noqa: BLE001
                logger.exception("streamlit.run_agent failed")
                fallback = {
                    "answer": f"Run failed: {exc}",
                    "confidence": "low",
                    "intent": "unknown",
                    "used_tools": [],
                    "generated_sql": "",
                    "tool_history": [],
                    "errors": [{"category": "SYNTHESIS_ERROR", "message": str(exc)}],
                    "total_token_usage": 0,
                    "total_cost_usd": 0.0,
                }
                pending_item["status"] = "failed"
                pending_item["content"] = fallback["answer"]
                pending_item["result"] = fallback
                status.update(label="Failed", state="error")
                st.error(fallback["answer"])

    st.session_state["is_processing"] = False
    st.session_state["current_assistant_index"] = None
    st.rerun()


_init_state()

with st.sidebar:
    # Backend connectivity indicator
    import os

    backend_url = os.getenv("BACKEND_URL", "http://localhost:8001")
    if _get_backend_health():
        st.success(f"✅ Backend: `{backend_url}`", icon=None)
    else:
        st.error(f"❌ Backend offline: `{backend_url}`")
        st.info("Run: `uvicorn backend.main:app --port 8001`")

    st.subheader("Session")
    selected_version = st.selectbox(
        "Graph Version",
        options=["v1", "v2", "v3"],
        index=["v1", "v2", "v3"].index(st.session_state.get("graph_version", "v2")),
    )
    st.session_state["graph_version"] = selected_version
    st.write(f"Thread ID: `{st.session_state.get('thread_id', 'N/A')[:8]}...`")
    st.write(f"Pending queue: `{len(st.session_state['pending_queries'])}`")
    if st.session_state["is_processing"]:
        st.write("Status: `processing`")
    else:
        st.write("Status: `idle`")

    if st.button(
        "🔄 New Conversation",
        use_container_width=True,
        help="Start fresh without memory of previous messages",
    ):
        st.session_state["thread_id"] = str(uuid.uuid4())
        st.session_state["chat_history"] = []
        st.session_state["pending_queries"] = []
        st.session_state["is_processing"] = False
        st.session_state["current_assistant_index"] = None
        logger.info(
            "streamlit.new_conversation thread={thread}",
            thread=st.session_state["thread_id"],
        )
        st.rerun()

    st.divider()
    st.subheader("Context Input")

    user_ctx = st.text_area(
        "Semantic Context",
        value=st.session_state.get("user_semantic_context", ""),
        placeholder="Nhập ngữ cảnh nghiệp vụ chung (vd: 'Doanh số tháng này đã giảm do...')",
        height=80,
        help="Ngữ cảnh chung giúp agent hiểu rõ hơn câu hỏi của bạn",
    )
    st.session_state["user_semantic_context"] = user_ctx

    st.divider()
    st.subheader("📁 Data Files")

    # ── Display existing pairs ───────────────────────────────────────────
    pairs = st.session_state["csv_pairs"]
    for i, pair in enumerate(pairs):
        col_name, col_remove = st.columns([4, 1])
        with col_name:
            st.markdown(f"📄 `{pair['name']}`")
        with col_remove:
            if st.button("✕", key=f"remove_{pair['id']}", help="Remove this file"):
                st.session_state["csv_pairs"].pop(i)
                st.rerun()
        new_ctx = st.text_area(
            "context",
            value=pair["context"],
            key=f"ctx_{pair['id']}",
            placeholder="Mô tả nghiệp vụ cho file này (optional)...",
            height=60,
            label_visibility="collapsed",
        )
        st.session_state["csv_pairs"][i]["context"] = new_ctx
        st.divider()

    # ── New file upload ──────────────────────────────────────────────────
    new_file = st.file_uploader(
        "Thêm CSV file",
        type=["csv"],
        accept_multiple_files=False,
        key=f"uploader_{st.session_state['uploader_key']}",
        help="Upload từng file một, kèm ngữ cảnh nghiệp vụ tương ứng",
    )
    new_ctx_input = st.text_area(
        "Mô tả nghiệp vụ (optional)",
        key=f"new_ctx_{st.session_state['uploader_key']}",
        placeholder="Ví dụ: 'Bảng đơn hàng B2C. amount là GMV chưa trừ hoàn.'",
        height=60,
    )
    if new_file is not None:
        if st.button("➕ Thêm vào danh sách", use_container_width=True):
            st.session_state["csv_pairs"].append(
                {
                    "id": str(uuid.uuid4())[:8],
                    "name": new_file.name,
                    "data": new_file.getvalue(),
                    "context": new_ctx_input.strip(),
                }
            )
            st.session_state["uploader_key"] += 1  # reset the uploader widget
            st.rerun()

    if pairs and st.button("🗑 Xoá tất cả files", use_container_width=True):
        st.session_state["csv_pairs"] = []
        st.session_state["uploader_key"] += 1
        st.rerun()

    st.divider()
    _render_sample_queries()
    if st.button("Clear Chat History", use_container_width=True):
        st.session_state["chat_history"] = []
        st.session_state["pending_queries"] = []
        st.session_state["is_processing"] = False
        st.session_state["current_assistant_index"] = None
        # Note: thread_id is preserved to keep conversation memory
        logger.info("streamlit.session cleared")
        st.rerun()

for message in st.session_state["chat_history"]:
    role = message.get("role", "assistant")
    with st.chat_message(role):
        if role == "user":
            st.write(message.get("content", ""))
            continue
        if message.get("status") == "thinking":
            st.write("Thinking...")
        result = message.get("result")
        if result:
            _render_result(result)
        else:
            st.write(message.get("content", ""))

query = st.chat_input("Hỏi về metrics/KPI/trend...", disabled=False)
if query and query.strip():
    _append_user_query(query)
    st.rerun()

_schedule_next_if_needed()
_run_current_query_if_needed()
