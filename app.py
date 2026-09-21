# Streamlit interface for the analytics agent

import streamlit as st
import pandas as pd

from agent.loop import solve

from agent.data import load_data


# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Data Analyst Agent",
    page_icon="",
    layout="wide",
)


# ── Load data once ─────────────────────────────────────────────────────────


@st.cache_data
def get_data():
    return load_data()


try:
    df = get_data()
except FileNotFoundError:
    st.error("CSV file not found. Check DATA_PATH in config.py.")
    st.stop()

# ── Sidebar: dataset reference ─────────────────────────────────────────────
with st.sidebar:
    st.subheader("Dataset")
    st.caption(f"{len(df):,} rows · {len(df.columns)} columns")

    st.markdown("**Columns**")
    schema = pd.DataFrame({
        "Column": df.columns,
        "Type": [str(t) for t in df.dtypes],
    })
    st.dataframe(schema, hide_index=True, use_container_width=True)

    st.divider()

    st.markdown("**Not supported**")
    st.caption(
        "This assistant returns aggregated summaries only. "
        "It will decline requests for:"
    )
    st.markdown(
        "- Individual records or raw rows\n"
        "- Data about one specific order or customer\n"
        "- Full table views or exports\n"
        "- Anything not present in the dataset"
    )


# ── Header ─────────────────────────────────────────────────────────────────
st.title("Data Analyst Agent")
st.caption(
    "Ask a question about the dataset. The agent writes and runs pandas "
    "code, then checks the result before returning it."
)


# ── Example questions (clickable) ──────────────────────────────────────────
EXAMPLES = [
    "What is the total revenue?",
    "Average revenue per region",
    "Revenue by product_category",
    "How many orders per payment method?",
]

st.markdown("**Try one of these**")
cols = st.columns(len(EXAMPLES))
clicked = None
for col, example in zip(cols, EXAMPLES):
    if col.button(example, use_container_width=True):
        clicked = example

st.divider()


# ── Chat history ───────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg.get("is_table"):
            st.dataframe(msg["content"], use_container_width=True)
        else:
            st.markdown(msg["content"])
        if msg.get("rejected"):
            st.info(msg["rejected"])


# ── Handle input ───────────────────────────────────────────────────────────
question = st.chat_input("Ask about the data...") or clicked

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Analysing..."):
            try:
                result = solve(question, df, verbose=False)
            except Exception as e:
                import traceback
                result = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"

        # A string result is the agent's rejection reason; anything else is
        # a computed answer.
        if isinstance(result, str):
            st.warning(result)
            st.session_state.messages.append({
                "role": "assistant",
                "content": "Request declined.",
                "rejected": result,
            })

        elif isinstance(result, pd.DataFrame):
            st.dataframe(result, use_container_width=True)
            st.session_state.messages.append({
                "role": "assistant",
                "content": result,
                "is_table": True,
            })

        elif isinstance(result, pd.Series):
            st.dataframe(result.to_frame(), use_container_width=True)
            st.session_state.messages.append({
                "role": "assistant",
                "content": result.to_frame(),
                "is_table": True,
            })

        else:
            answer = f"**{result:,.2f}**" if isinstance(result, float) else f"**{result}**"
            st.markdown(answer)
            st.session_state.messages.append({
                "role": "assistant",
                "content": answer,
            })