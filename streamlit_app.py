from __future__ import annotations

from typing import Any

import streamlit as st

from app.logger import logger
from app.main import run_query


st.set_page_config(page_title="DA Agent Lab", page_icon="📊", layout="wide")
st.title("DA Agent Lab")
st.caption("LangGraph DA Agent chat with trace visibility")


def run_agent(
    user_query: str,
    user_semantic_context: str | None = None,
    uploaded_files: list[str] | None = None,
    uploaded_file_data: list[dict[str, Any]] | None = None,
) -> dict:
    logger.info("streamlit.run_agent start query_len={len}", len=len(user_query))
    payload = run_query(
        user_query=user_query,
        recursion_limit=25,
        user_semantic_context=user_semantic_context,
        uploaded_files=uploaded_files,
        uploaded_file_data=uploaded_file_data,
    )
    logger.info(
        "streamlit.run_agent done run_id={run_id} intent={intent}",
        run_id=payload.get("run_id", "unknown"),
        intent=payload.get("intent", "unknown"),
    )
    return payload


def _init_state() -> None:
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("pending_queries", [])
    st.session_state.setdefault("is_processing", False)
    st.session_state.setdefault("current_assistant_index", None)
    st.session_state.setdefault("user_semantic_context", "")
    st.session_state.setdefault("uploaded_csv_files", [])


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

    with st.expander("Agent Logs", expanded=False):
        tabs = st.tabs(["SQL", "Trace", "Errors", "Raw"])
        with tabs[0]:
            st.code(result.get("generated_sql", ""), language="sql")
        with tabs[1]:
            st.json(result.get("tool_history", []))
        with tabs[2]:
            st.json(result.get("errors", []))
        with tabs[3]:
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
    uploaded_files_raw = st.session_state.get("uploaded_csv_files", [])
    uploaded_filenames: list[str] = [f["name"] for f in uploaded_files_raw]
    uploaded_file_data: list[dict[str, Any]] = [
        {"name": f["name"], "data": f["data"]}
        for f in uploaded_files_raw
        if f.get("data")
    ]

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
    st.subheader("Session")
    st.write(f"Pending queue: `{len(st.session_state['pending_queries'])}`")
    if st.session_state["is_processing"]:
        st.write("Status: `processing`")
    else:
        st.write("Status: `idle`")

    st.divider()
    st.subheader("Context Input")

    user_ctx = st.text_area(
        "Semantic Context",
        value=st.session_state.get("user_semantic_context", ""),
        placeholder="Nhập ngữ cảnh nghiệp vụ (vd: 'Doanh số tháng này đã giảm do...')",
        height=80,
        help="Ngữ cảnh 추가 giúp agent hiểu rõ hơn câu hỏi của bạn",
    )
    st.session_state["user_semantic_context"] = user_ctx

    uploaded_files = st.file_uploader(
        "Upload CSV files",
        type=["csv"],
        accept_multiple_files=True,
        help="Upload CSV files để agent tự động sinh bảng và ngữ cảnh",
    )
    if uploaded_files:
        st.session_state["uploaded_csv_files"] = [
            {"name": f.name, "data": f.getvalue()} for f in uploaded_files
        ]
        for f in uploaded_files:
            st.write(f"📄 {f.name}")
    else:
        st.session_state["uploaded_csv_files"] = []

    if st.button("Clear Context", use_container_width=True):
        st.session_state["user_semantic_context"] = ""
        st.session_state["uploaded_csv_files"] = []
        st.rerun()

    st.divider()
    _render_sample_queries()
    if st.button("Clear Chat History", use_container_width=True):
        st.session_state["chat_history"] = []
        st.session_state["pending_queries"] = []
        st.session_state["is_processing"] = False
        st.session_state["current_assistant_index"] = None
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
