"""Job Market Pipeline — AI-generated market report page."""

import streamlit as st

from shared import inject_css, load_all_reports

st.set_page_config(page_title="Market Report — Remote Job Tracker", page_icon="📰", layout="wide")
inject_css()

st.title("Market Report")
st.caption("Written daily by an LLM (Groq / Llama) from the pipeline's latest analysis.")

reports_df = load_all_reports()

if reports_df.empty:
    st.info("No report generated yet — run generate_report.py first.")
    st.stop()

latest = reports_df.iloc[0]
st.subheader(f"Latest — {latest['generated_at'].strftime('%b %d, %Y %H:%M UTC')}")
st.markdown(
    f"<div style='background:#131B2E;border:1px solid #1E293B;border-radius:10px;"
    f"padding:24px 28px;line-height:1.6;'>{latest['report_text']}</div>",
    unsafe_allow_html=True,
)

if len(reports_df) > 1:
    st.divider()
    st.subheader("Past reports")
    for _, row in reports_df.iloc[1:].iterrows():
        with st.expander(row["generated_at"].strftime("%b %d, %Y %H:%M UTC")):
            st.markdown(row["report_text"])

st.divider()
st.page_link("app.py", label="← Back to overview", icon="🧭")