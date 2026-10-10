"""Web UI:  streamlit run streamlit_app.py"""
from pathlib import Path

import pandas as pd
import streamlit as st

from clarisql.config import DEFAULT_PROVIDER, MAX_ROWS, MODELS
from clarisql.db import load_schema, run_select, set_description
from clarisql.engine import TextToSQLEngine
from clarisql.llm import LLMClient
from clarisql.loader import clean_name, load_dataframe, read_csv
from clarisql.notes import load_notes, save_notes

st.set_page_config(page_title="ClariSQL", page_icon="🧠", layout="wide")

# Add your own starter questions here; they appear above the automatic ones.
CUSTOM_EXAMPLES: list[str] = []
MAX_UPLOAD_MB = 50


# ------------------------------------------------------------------ helpers
def get_schema():
    if "schema" not in st.session_state:
        with st.spinner("Reading database schema..."):
            st.session_state.schema = load_schema()
    return st.session_state.schema


def refresh_schema() -> None:
    st.session_state.schema = load_schema()
    st.session_state.engines = {}  # engines hold the old schema text


def get_engine(provider: str) -> TextToSQLEngine:
    engines = st.session_state.setdefault("engines", {})
    if provider not in engines:
        schema = get_schema()
        engines[provider] = TextToSQLEngine(LLMClient(provider), schema.text, schema.tables, run_select, MAX_ROWS)
    return engines[provider]


def example_questions(schema) -> list[str]:
    auto = [f"How many rows are in the {t} table?" for t in sorted(schema.tables)[:3]]
    return CUSTOM_EXAMPLES + auto + ["Show me the top records", "Give me an overview of this data"]


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
st.session_state.setdefault("notes_text", load_notes())

with st.sidebar:
    st.title("🧠 ClariSQL")
    st.caption("Text-to-SQL with a Clarification Engine")

    for kind, msg in st.session_state.pop("flash", []):
        getattr(st, kind)(msg)

    provider = st.selectbox(
        "LLM provider", list(MODELS), index=list(MODELS).index(DEFAULT_PROVIDER) if DEFAULT_PROVIDER in MODELS else 0
    )
    st.caption(f"Model: `{MODELS[provider]}`")
    if st.button("Start new conversation"):
        st.session_state.chat = []
        for e in st.session_state.get("engines", {}).values():
            e.reset()
        st.rerun()

    schema = get_schema()
    st.divider()
    st.markdown("**Your data**")

    with st.expander("📂 Upload CSV files"):
        files = st.file_uploader("Choose one or more CSV files", type=["csv"], accept_multiple_files=True)
        replace = st.checkbox("Replace tables that already exist")
        st.caption("Each file becomes a table named after the file. Files with matching column names (like customer_id) can be joined.")
        if st.button("Load into database", disabled=not files):
            flash = []
            with st.spinner("Loading..."):
                for f in files:
                    table = clean_name(Path(f.name).stem, prefix="t_")
                    try:
                        if f.size > MAX_UPLOAD_MB * 1024 * 1024:
                            raise ValueError(f"file is larger than {MAX_UPLOAD_MB} MB")
                        rows, cols = load_dataframe(read_csv(f), table, replace=replace)
                        flash.append(("success", f"Loaded {rows:,} rows × {cols} columns into '{table}'."))
                    except FileExistsError:
                        flash.append(("warning", f"Table '{table}' already exists. Tick “Replace tables that already exist” to overwrite it."))
                    except Exception as exc:
                        flash.append(("error", f"{f.name}: {exc}"))
                refresh_schema()
            st.session_state.flash = flash
            st.rerun()

    with st.expander("📝 Notes about the data"):
        st.caption("Tell the AI what terms mean, e.g. “Revenue = quantity × unit_price” or “High attendance means 85 or more”. Applies to the next question.")
        st.text_area("Notes", key="notes_text", height=220, label_visibility="collapsed")
        if st.button("Save notes to file"):
            save_notes(st.session_state.notes_text)
            st.success("Saved to notes.md")

    with st.expander("🏷️ Describe tables and columns"):
        if schema.columns:
            table = st.selectbox("Table", sorted(schema.columns))
            col = st.selectbox("Column", ["(whole table)"] + schema.columns[table])
            key = "" if col == "(whole table)" else col
            desc = st.text_input(
                "What does it mean?",
                value=schema.comments.get((table, key), ""),
                key=f"desc_{table}_{key}",
                placeholder="e.g. Final exam mark out of 100",
            )
            st.caption("Saved inside the database. Leave empty to remove a description.")
            if st.button("Save description"):
                try:
                    set_description(table, key, desc)
                    refresh_schema()
                    st.session_state.flash = [("success", "Description saved.")]
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        else:
            st.caption("No tables yet. Upload a CSV first.")

    if st.button("🔄 Refresh schema"):
        refresh_schema()
        st.rerun()
    with st.expander("Database schema"):
        st.code(schema.text, language="sql")

    st.divider()
    st.markdown("**Try these**")
    for ex in example_questions(schema):
        if st.button(ex, key=f"ex_{ex}"):
            st.session_state.pending = ex

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
            engine = get_engine(provider)
            engine.notes = st.session_state.notes_text
            with st.spinner("Thinking..."):
                res = engine.ask(prompt)
            entry = res.__dict__
        except Exception as exc:
            entry = {"status": "error", "error": str(exc)}
        render(entry)
    st.session_state.chat.append({"role": "assistant", "entry": entry})
