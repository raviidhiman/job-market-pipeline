"""Shared connection, data loading, and styling helpers for the dashboard."""

import os
from urllib.parse import quote_plus

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine

# ── Design tokens ────────────────────────────────────────────────────────
BG = "#0B1120"
CARD = "#131B2E"
ACCENT_TEAL = "#2DD4BF"
ACCENT_AMBER = "#F59E0B"
TEXT = "#E2E8F0"
MUTED = "#64748B"
STATUS_COLORS = {"active": "#2DD4BF", "cooling": "#F59E0B", "stale": "#EF4444"}
SOURCE_COLORS = {"remoteok": "#2DD4BF", "arbeitnow": "#F59E0B", "jobicy": "#818CF8"}


def inject_css():
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Inter:wght@400;500;600&display=swap');

        html, body, [class*="css"] {{
            font-family: 'Inter', sans-serif;
        }}
        h1 {{
            font-family: 'Fraunces', serif !important;
            font-weight: 600 !important;
            letter-spacing: -0.02em;
        }}
        h2, h3 {{
            font-family: 'Fraunces', serif !important;
            font-weight: 500 !important;
        }}
        [data-testid="stMetric"] {{
            background: {CARD};
            border: 1px solid #1E293B;
            border-radius: 10px;
            padding: 16px 18px;
        }}
        [data-testid="stMetricLabel"] {{
            color: {MUTED};
        }}
        [data-testid="stMetricValue"] {{
            color: {TEXT};
            font-family: 'Fraunces', serif;
        }}
        section[data-testid="stSidebar"] {{
            background: {CARD};
            border-right: 1px solid #1E293B;
        }}
        .stPlotlyChart {{
            background: {CARD};
            border: 1px solid #1E293B;
            border-radius: 10px;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def plotly_layout_defaults(fig, height=None):
    fig.update_layout(
        paper_bgcolor=CARD,
        plot_bgcolor=CARD,
        font_color=TEXT,
        margin=dict(t=40, b=70, l=10, r=10),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            orientation="h",
            yanchor="top", y=-0.3,
            xanchor="center", x=0.5,
            title=None,
        ),
    )
    if height:
        fig.update_layout(height=height)
    fig.update_xaxes(gridcolor="#1E293B", zerolinecolor="#1E293B")
    fig.update_yaxes(gridcolor="#1E293B", zerolinecolor="#1E293B")
    return fig


# ── Connection ───────────────────────────────────────────────────────────
def metric_card(label: str, value: str, delta: str = None, delta_positive: bool = True):
    delta_color = "#2DD4BF" if delta_positive else "#EF4444"
    delta_html = (
        f'<div style="margin-top:8px;display:inline-block;background:{delta_color}22;'
        f'color:{delta_color};font-size:0.8rem;font-weight:600;padding:3px 10px;'
        f'border-radius:999px;">{delta}</div>'
        if delta else
        '<div style="margin-top:8px;height:26px;"></div>'
    )
    st.markdown(
        f"""
        <div style="background:{CARD};border:1px solid #1E293B;border-radius:10px;
                    padding:16px 18px;height:118px;box-sizing:border-box;
                    display:block;overflow:hidden;margin-bottom:24px;">
            <div style="color:{MUTED};font-size:0.85rem;white-space:nowrap;
                        overflow:hidden;text-overflow:ellipsis;">{label}</div>
            <div style="font-family:'Fraunces',serif;font-size:1.7rem;color:{TEXT};
                        margin-top:4px;line-height:1.2;white-space:nowrap;
                        overflow:hidden;text-overflow:ellipsis;">{value}</div>
            {delta_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def get_secret(key: str) -> str:
    try:
        return st.secrets[key]
    except Exception:
        return os.environ.get(key, "")


@st.cache_resource
def get_engine():
    host = get_secret("SUPABASE_DB_HOST")
    port = get_secret("SUPABASE_DB_PORT") or "6543"
    name = get_secret("SUPABASE_DB_NAME") or "postgres"
    user = get_secret("SUPABASE_DB_USER")
    password = get_secret("SUPABASE_DB_PASSWORD")

    if not all([host, user, password]):
        st.error(
            "Missing database credentials. Set SUPABASE_DB_HOST, SUPABASE_DB_USER, "
            "and SUPABASE_DB_PASSWORD as environment variables or Streamlit secrets."
        )
        st.stop()

    url = f"postgresql+psycopg2://{user}:{quote_plus(password)}@{host}:{port}/{name}"
    return create_engine(url)


# ── Data loaders (shared cache across pages) ────────────────────────────
@st.cache_data(ttl=600)
def load_raw_jobs() -> pd.DataFrame:
    engine = get_engine()
    df = pd.read_sql("SELECT * FROM raw_jobs", engine)
    df["scraped_at"] = pd.to_datetime(df["scraped_at"], utc=True)
    df["last_seen_at"] = pd.to_datetime(df["last_seen_at"], utc=True)
    return df


@st.cache_data(ttl=600)
def load_skill_frequency() -> pd.DataFrame:
    engine = get_engine()
    return pd.read_sql("""
        SELECT skill, job_count, computed_at FROM analysis_skill_frequency
        WHERE computed_at = (SELECT MAX(computed_at) FROM analysis_skill_frequency)
        ORDER BY job_count DESC
    """, engine)


@st.cache_data(ttl=600)
def load_role_freshness() -> pd.DataFrame:
    engine = get_engine()
    return pd.read_sql("""
        SELECT status, COUNT(*) as count FROM analysis_role_freshness
        WHERE computed_at = (SELECT MAX(computed_at) FROM analysis_role_freshness)
        GROUP BY status
    """, engine)


@st.cache_data(ttl=600)
def load_all_reports() -> pd.DataFrame:
    engine = get_engine()
    return pd.read_sql(
        "SELECT report_text, generated_at FROM reports ORDER BY generated_at DESC",
        engine,
    )