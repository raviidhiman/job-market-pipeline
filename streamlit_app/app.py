"""
Job Market Pipeline — Streamlit Dashboard (Overview page)

Run locally:
    streamlit run app.py

Deploy: push to GitHub, connect the repo on share.streamlit.io, and add
SUPABASE_DB_HOST / SUPABASE_DB_USER / SUPABASE_DB_PASSWORD as "Secrets"
in the Streamlit Cloud app settings (see secrets.toml.example).
"""

import datetime as dt

import plotly.express as px
import streamlit as st

from shared import (
    inject_css, plotly_layout_defaults, metric_card, load_raw_jobs, load_skill_frequency,
    load_role_freshness, STATUS_COLORS, SOURCE_COLORS,
)

st.set_page_config(page_title="Remote Job Market Tracker", page_icon="🧭", layout="wide")
inject_css()

raw_df = load_raw_jobs()
skill_df = load_skill_frequency()
freshness_df = load_role_freshness()

if raw_df.empty:
    st.warning("No data yet — the pipeline hasn't run, or hasn't found any jobs.")
    st.stop()

# ── Sidebar filters ─────────────────────────────────────────────────────
st.sidebar.header("Filters")
all_sources = sorted(raw_df["source"].unique())
selected_sources = st.sidebar.multiselect("Sources", all_sources, default=all_sources)
skill_search = st.sidebar.text_input("Search skills/tags", "")
top_n = st.sidebar.slider("Top N skills to show", 5, 30, 15)

st.sidebar.divider()
st.sidebar.caption(
    "Pipeline: n8n scrapes RemoteOK, Arbeitnow, and Jobicy daily; "
    "Python computes skill frequency and role freshness; "
    "Groq (Llama) writes the market summary."
)

filtered_raw = raw_df[raw_df["source"].isin(selected_sources)] if selected_sources else raw_df
filtered_skills = skill_df[skill_df["skill"].str.contains(skill_search, case=False, na=False)] if skill_search else skill_df

# ── Header ──────────────────────────────────────────────────────────────
st.title("The Remote Work Ledger")
st.caption(
    f"A running account of the remote job market — tracking {', '.join(all_sources)} — "
    f"last updated {raw_df['last_seen_at'].max().strftime('%b %d, %Y %H:%M UTC')}"
)

# ── Top metrics with trend deltas ──────────────────────────────────────
recent_cutoff = raw_df["scraped_at"].max() - dt.timedelta(days=1)
new_last_day = int((raw_df["scraped_at"] >= recent_cutoff).sum())

col1, col2, col3, col4 = st.columns(4)
with col1:
    metric_card("Total jobs tracked", f"{len(filtered_raw):,}", delta=f"↑ +{new_last_day} last 24h")
with col2:
    metric_card("Sources", str(filtered_raw["source"].nunique()))
active_count = int(freshness_df.loc[freshness_df["status"] == "active", "count"].sum()) if not freshness_df.empty else 0
with col3:
    metric_card("Active postings", f"{active_count:,}")
stale_count = int(freshness_df.loc[freshness_df["status"] == "stale", "count"].sum()) if not freshness_df.empty else 0
with col4:
    metric_card("Stale postings", f"{stale_count:,}")

st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
col5, col6, col7 = st.columns(3)
top_skill_row = skill_df.iloc[0] if not skill_df.empty else None
with col5:
    metric_card("Top skill right now", top_skill_row["skill"] if top_skill_row is not None else "—",
                delta=f"{top_skill_row['job_count']} postings" if top_skill_row is not None else None)
top_source_counts = filtered_raw["source"].value_counts()
with col6:
    metric_card("Top source right now", top_source_counts.index[0] if not top_source_counts.empty else "—",
                delta=f"{top_source_counts.iloc[0]} jobs" if not top_source_counts.empty else None)
days_span = max((raw_df["scraped_at"].max() - raw_df["scraped_at"].min()).days, 1)
with col7:
    metric_card("Avg new jobs / day", f"{len(raw_df) / days_span:,.0f}")

st.divider()

# ── Time-window explorer ───────────────────────────────────────────────
st.subheader("Time-window explorer")

min_date = raw_df["scraped_at"].min().date()
max_date = raw_df["scraped_at"].max().date()
date_range = st.date_input("Select a date range", value=(min_date, max_date), min_value=min_date, max_value=max_date)
start_date, end_date = date_range if len(date_range) == 2 else (min_date, max_date)

view_mode = st.radio(
    "View", ["Newly posted", "Still active"], horizontal=True,
    help=(
        "Newly posted = jobs first seen on that day (can look flat after day one, "
        "since most job IDs don't repeat as 'new'). Still active = jobs confirmed "
        "live on that day, based on the most recent scrape that found them."
    ),
)

mask = (
    (filtered_raw["scraped_at"].dt.date >= start_date)
    & (filtered_raw["scraped_at"].dt.date <= end_date)
)
windowed_df = filtered_raw[mask]

explorer_col1, explorer_col2 = st.columns(2)

with explorer_col1:
    date_col = "scraped_at" if view_mode == "Newly posted" else "last_seen_at"
    postings_by_day = (
        windowed_df.groupby([windowed_df[date_col].dt.date, "source"])
        .size().reset_index(name="count").rename(columns={date_col: "date"})
    )
    if not postings_by_day.empty:
        fig = px.line(
            postings_by_day, x="date", y="count", color="source", markers=True,
            title=f"{view_mode} per day, by source", color_discrete_map=SOURCE_COLORS,
        )
        st.plotly_chart(plotly_layout_defaults(fig), use_container_width=True, config={"responsive": False})
    else:
        st.info("No postings in this date range.")

with explorer_col2:
    by_source = windowed_df["source"].value_counts().reset_index()
    by_source.columns = ["source", "count"]
    if not by_source.empty:
        fig = px.bar(
            by_source, x="source", y="count", title="Jobs by source — click a bar to filter",
            color="source", color_discrete_map=SOURCE_COLORS,
        )
        fig.update_layout(showlegend=False)
        event = st.plotly_chart(
            plotly_layout_defaults(fig), use_container_width=True,
            config={"responsive": False}, on_select="rerun", selection_mode="points",
            key="source_chart",
        )
        if event and event.selection and event.selection.points:
            st.session_state["clicked_source"] = event.selection.points[0]["x"]

st.divider()

# ── Skills + freshness ──────────────────────────────────────────────────
skills_col, freshness_col = st.columns(2)

with skills_col:
    st.subheader("Top skills / tags")
    st.caption("Click a bar to filter the table below")
    if not filtered_skills.empty:
        fig = px.bar(
            filtered_skills.head(top_n).sort_values("job_count"),
            x="job_count", y="skill", orientation="h",
            color_discrete_sequence=["#2DD4BF"],
        )
        fig.update_layout(margin=dict(t=10, b=10, l=10, r=10))
        event = st.plotly_chart(
            plotly_layout_defaults(fig, height=480), use_container_width=True,
            config={"responsive": False}, on_select="rerun", selection_mode="points",
            key="skills_chart",
        )
        if event and event.selection and event.selection.points:
            st.session_state["clicked_skill"] = event.selection.points[0]["y"]
    else:
        st.info("No skills matched your search.")

with freshness_col:
    st.subheader("Role freshness")
    st.caption("How long postings have stayed live")
    if not freshness_df.empty:
        fig = px.pie(
            freshness_df, names="status", values="count", hole=0.55,
            color="status", color_discrete_map=STATUS_COLORS,
        )
        fig.update_layout(margin=dict(t=10, b=60, l=10, r=10))
        st.plotly_chart(plotly_layout_defaults(fig, height=480), use_container_width=True, config={"responsive": False})
    else:
        st.info("No freshness data yet.")

# ── Job table ────────────────────────────────────────────────────────────
st.divider()
table_col_a, table_col_b = st.columns([4, 1])
with table_col_a:
    st.subheader("Browse postings")
with table_col_b:
    if st.session_state.get("clicked_source") or st.session_state.get("clicked_skill"):
        if st.button("✕ Clear selection", use_container_width=True):
            st.session_state.pop("clicked_source", None)
            st.session_state.pop("clicked_skill", None)
            st.rerun()

table_df = windowed_df.copy()
active_filters = []
if st.session_state.get("clicked_source"):
    table_df = table_df[table_df["source"] == st.session_state["clicked_source"]]
    active_filters.append(f"source = {st.session_state['clicked_source']}")
if st.session_state.get("clicked_skill"):
    skill = st.session_state["clicked_skill"]
    table_df = table_df[table_df["tags"].apply(lambda t: skill in [str(x).lower() for x in t] if isinstance(t, list) else False)]
    active_filters.append(f"skill = {skill}")

if active_filters:
    st.caption("Filtered by: " + " · ".join(active_filters))

show_cols = ["title", "company", "location", "source", "tags", "url", "scraped_at"]
st.dataframe(
    table_df[show_cols].sort_values("scraped_at", ascending=False),
    use_container_width=True, hide_index=True, height=350,
    column_config={"url": st.column_config.LinkColumn("url")},
)

st.page_link("pages/1_Report.py", label="Read the latest market report →", icon="📰")