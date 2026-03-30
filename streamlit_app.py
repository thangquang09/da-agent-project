from __future__ import annotations

import json

import streamlit as st

from app.main import run_query


st.set_page_config(page_title="DA Agent Lab", page_icon="📊", layout="wide")
st.title("DA Agent Lab")
st.caption("SQL-first LangGraph demo with debug traces")


def run_agent(user_query: str) -> dict:
    payload = run_query(user_query=user_query, recursion_limit=25)
    return payload


if "history" not in st.session_state:
    st.session_state["history"] = []


with st.form("query_form"):
    query = st.text_input("Ask a data question", placeholder="DAU 7 ngày gần đây như thế nào?")
    submitted = st.form_submit_button("Run")

if submitted and query.strip():
    result = run_agent(query.strip())
    st.session_state["history"].append({"query": query.strip(), "result": result})


if st.session_state["history"]:
    latest = st.session_state["history"][-1]
    result = latest["result"]

    st.subheader("Latest Result")
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Confidence", str(result.get("confidence", "unknown")).upper())
    col2.metric("Intent", str(result.get("intent", "unknown")).upper())
    col3.metric("Tools Used", len(result.get("used_tools", [])))
    col4.metric("Tokens", int(result.get("total_token_usage", 0) or 0))
    col5.metric("Cost (USD)", f"{float(result.get('total_cost_usd', 0) or 0):.6f}")

    tabs = st.tabs(["Answer", "SQL", "Trace", "Errors"])

    with tabs[0]:
        st.write(result.get("answer", "No answer"))
        st.caption(f"Run ID: {result.get('run_id', '-')}")

    with tabs[1]:
        st.code(result.get("generated_sql", ""), language="sql")

    with tabs[2]:
        st.json(result.get("tool_history", []))

    with tabs[3]:
        st.json(result.get("errors", []))

st.subheader("History")
for idx, item in enumerate(reversed(st.session_state["history"]), start=1):
    with st.expander(f"{idx}. {item['query']}"):
        st.code(item["result"].get("generated_sql", ""), language="sql")
        st.write(item["result"].get("answer", ""))
        st.json(
            {
                "confidence": item["result"].get("confidence"),
                "intent": item["result"].get("intent"),
                "used_tools": item["result"].get("used_tools", []),
            }
        )
        st.text(json.dumps(item["result"], ensure_ascii=False))
