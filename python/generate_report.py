"""
Job Market Pipeline — Report Generation
Pulls the latest skill-frequency and role-freshness results from Supabase,
sends a summary to Groq's free Llama API, and asks it to write a short,
plain-English market report. Saves the report back into a `reports` table.

Run manually:
    python3 generate_report.py

Requires GROQ_API_KEY plus the same SUPABASE_DB_* vars as analyze_jobs.py.
"""

import os
import sys
from datetime import datetime, timezone
from urllib.parse import quote_plus

import pandas as pd
import requests
from sqlalchemy import create_engine, text

# ── Config ────────────────────────────────────────────────────────────────
DB_HOST = os.environ.get("SUPABASE_DB_HOST")
DB_PORT = os.environ.get("SUPABASE_DB_PORT", "6543")
DB_NAME = os.environ.get("SUPABASE_DB_NAME", "postgres")
DB_USER = os.environ.get("SUPABASE_DB_USER")
DB_PASSWORD = os.environ.get("SUPABASE_DB_PASSWORD")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

REQUIRED = {
    "SUPABASE_DB_HOST": DB_HOST,
    "SUPABASE_DB_USER": DB_USER,
    "SUPABASE_DB_PASSWORD": DB_PASSWORD,
    "GROQ_API_KEY": GROQ_API_KEY,
}
missing = [k for k, v in REQUIRED.items() if not v]
if missing:
    sys.exit(f"Missing required environment variables: {', '.join(missing)}")

DB_URL = f"postgresql+psycopg2://{DB_USER}:{quote_plus(DB_PASSWORD)}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(DB_URL)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"  # fast + free-tier friendly (llama-3.1-8b-instant was deprecated)


def load_latest_analysis():
    """Pull the most recent skill-frequency and role-freshness snapshots."""
    skill_df = pd.read_sql("""
        SELECT skill, job_count FROM analysis_skill_frequency
        WHERE computed_at = (SELECT MAX(computed_at) FROM analysis_skill_frequency)
        ORDER BY job_count DESC
        LIMIT 15
    """, engine)

    freshness_df = pd.read_sql("""
        SELECT status, COUNT(*) as count FROM analysis_role_freshness
        WHERE computed_at = (SELECT MAX(computed_at) FROM analysis_role_freshness)
        GROUP BY status
    """, engine)

    total_jobs = pd.read_sql("SELECT COUNT(*) as total FROM raw_jobs", engine)["total"][0]
    by_source = pd.read_sql("""
        SELECT source, COUNT(*) as count FROM raw_jobs GROUP BY source
    """, engine)

    return skill_df, freshness_df, total_jobs, by_source


def build_prompt(skill_df, freshness_df, total_jobs, by_source) -> str:
    skills_text = "\n".join(f"- {row.skill}: {row.job_count} postings" for row in skill_df.itertuples())
    freshness_text = "\n".join(f"- {row.status}: {row.count} jobs" for row in freshness_df.itertuples())
    source_text = "\n".join(f"- {row.source}: {row.count} jobs" for row in by_source.itertuples())

    return f"""You are writing a short market summary for a remote job-market analytics dashboard.

Data snapshot:
Total jobs tracked: {total_jobs}

Jobs by source:
{source_text}

Top skills/tags by posting count:
{skills_text}

Role freshness breakdown:
{freshness_text}

Write a concise, plain-English summary (150-200 words) covering:
1. What the current remote job market looks like based on this data
2. Which skills/categories are most in demand right now
3. Any notable pattern in role freshness (active vs stale postings)

Do not invent numbers not shown above. Write for a general audience, not a technical one."""


def call_groq(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5,
        "max_tokens": 400,
    }
    response = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def save_report(report_text: str):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS reports (
                id SERIAL PRIMARY KEY,
                report_text TEXT,
                generated_at TIMESTAMP
            )
        """))
        conn.execute(
            text("INSERT INTO reports (report_text, generated_at) VALUES (:text, :ts)"),
            {"text": report_text, "ts": datetime.now(timezone.utc)},
        )
        # Keep only the single most recent report; delete everything older.
        conn.execute(text("""
            DELETE FROM reports
            WHERE id NOT IN (SELECT id FROM reports ORDER BY generated_at DESC LIMIT 1)
        """))
    print("Report saved to Supabase 'reports' table (older reports cleaned up).")


def main():
    skill_df, freshness_df, total_jobs, by_source = load_latest_analysis()

    if skill_df.empty:
        print("No analysis data found yet — run analyze_jobs.py first.")
        return

    prompt = build_prompt(skill_df, freshness_df, total_jobs, by_source)
    print("Calling Groq API...")
    report_text = call_groq(prompt)

    print("\n--- Generated Report ---\n")
    print(report_text)
    print("\n------------------------\n")

    save_report(report_text)


if __name__ == "__main__":
    main()