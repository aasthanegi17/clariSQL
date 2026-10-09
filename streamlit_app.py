"""Web UI:  streamlit run streamlit_app.py"""
import pandas as pd
import streamlit as st

from clarisql.config import DEFAULT_PROVIDER, MAX_ROWS, MODELS
from clarisql.db import load_schema, run_select
from clarisql.engine import TextToSQLEngine
from clarisql.llm import LLMClient

st.set_page_config(page_title="ClariSQL", page_icon="🧠", layout="wide")

EXAMPLES = [
    "How many customers do we have?",
    "Total revenue by product category",
    "Show me top customers",
    "Show recent orders",
    "Which payment method is used the most?",
]


@st.cache_resource(show_spinner="Reading database schema...")
def get_schema():
    return load_schema()


def get_engine(provider: str) -> TextToSQLEngine:
    engines = st.session_state.setdefault("engines", {})
    if provider not in engines:
        schema = get_schema()
        engines[provider] = TextToSQLEngine(LLMClient(provider), schema.text, schema.tables, run_select, MAX_ROWS)
    return engines[provider]


def render(entry: dict) -> None:
    if entry["status"] == "clarify":
        st.markdown("🤔 **I need a bit more detail before I write the query:**")
        for q in entry["questions"]:
            st.markdown(f"- {q}")
        st.caption("Reply in the chat box below. You can also say “you decide”.")
    elif entry["status"] == "error":
        st.error(entry["error"])
        if entry.get("sql"):
            st.code(entry["sql"], language="sql")
    else:
        for a in entry["assumptions"]:
            st.info(f"Assumption: {a}")
        st.code(entry["sql"], language="sql")
        df = pd.DataFrame(entry["rows"], columns=entry["columns"])
        st.dataframe(df, use_container_width=True)
        note = " (showing first rows only)" if entry["truncated"] else ""
        st.caption(f"{len(df)} rows{note} · {entry['repairs']} auto-repairs · {entry['latency_s']:.2f}s")


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.title("🧠 ClariSQL")
    st.caption("Text-to-SQL with a Clarification Engine")
    provider = st.selectbox(
        "LLM provider", list(MODELS), index=list(MODELS).index(DEFAULT_PROVIDER) if DEFAULT_PROVIDER in MODELS else 0
    )
    st.caption(f"Model: `{MODELS[provider]}`")
    if st.button("Start new conversation"):
        st.session_state.chat = []
        for e in st.session_state.get("engines", {}).values():
            e.reset()
        st.rerun()
    st.divider()
    st.markdown("**Try these**")
    for ex in EXAMPLES:
        if st.button(ex, key=ex):
            st.session_state.pending = ex
    with st.expander("Database schema"):
        st.code(get_schema().text, language="sql")

# --------------------------------------------------------------------- chat
st.session_state.setdefault("chat", [])
for item in st.session_state.chat:
    with st.chat_message(item["role"]):
        if item["role"] == "user":
            st.write(item["text"])
        else:
            render(item["entry"])

prompt = st.chat_input("Ask a question about the data...") or st.session_state.pop("pending", None)
if prompt:
    st.session_state.chat.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.write(prompt)
    with st.chat_message("assistant"):
        try:
            with st.spinner("Thinking..."):
                res = get_engine(provider).ask(prompt)
            entry = res.__dict__
        except Exception as exc:
            entry = {"status": "error", "error": str(exc)}
        render(entry)
    st.session_state.chat.append({"role": "assistant", "entry": entry})
