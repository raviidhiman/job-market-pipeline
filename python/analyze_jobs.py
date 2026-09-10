"""
Job Market Pipeline — Analysis Script
Pulls raw_jobs from Supabase, computes:
  1. Skill/tag frequency
  2. Role "freshness" tracking (still active vs. gone stale)
Writes results back into two new Postgres tables:
  - analysis_skill_frequency
  - analysis_role_freshness

Run manually first to confirm it works:
    python3 analyze_jobs.py

Then schedule it (cron on the VM, or GitHub Actions) to run daily.
"""

import os
import sys
from datetime import datetime, timezone
from collections import Counter
from urllib.parse import quote_plus

import pandas as pd
from sqlalchemy import create_engine, text

# ── Config ────────────────────────────────────────────────────────────────
# Reads connection info from environment variables so credentials never
# get committed to GitHub. Set these before running (see setup steps).
DB_HOST = os.environ.get("SUPABASE_DB_HOST")       # e.g. aws-0-ap-northeast-1.pooler.supabase.com
DB_PORT = os.environ.get("SUPABASE_DB_PORT", "6543")
DB_NAME = os.environ.get("SUPABASE_DB_NAME", "postgres")
DB_USER = os.environ.get("SUPABASE_DB_USER")       # e.g. postgres.zeibigytavhebanuzrjn
DB_PASSWORD = os.environ.get("SUPABASE_DB_PASSWORD")

REQUIRED = {
    "SUPABASE_DB_HOST": DB_HOST,
    "SUPABASE_DB_USER": DB_USER,
    "SUPABASE_DB_PASSWORD": DB_PASSWORD,
}
missing = [k for k, v in REQUIRED.items() if not v]
if missing:
    sys.exit(f"Missing required environment variables: {', '.join(missing)}")

DB_URL = f"postgresql+psycopg2://{DB_USER}:{quote_plus(DB_PASSWORD)}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(DB_URL)


def load_raw_jobs() -> pd.DataFrame:
    """Pull all rows from raw_jobs into a DataFrame."""
    df = pd.read_sql("SELECT * FROM raw_jobs", engine)
    print(f"Loaded {len(df)} rows from raw_jobs")
    return df


def compute_skill_frequency(df: pd.DataFrame) -> pd.DataFrame:
    """
    Count how often each tag/skill appears across all current job postings.
    'tags' is stored as a Postgres array, which pandas reads as a Python list.
    """
    counter = Counter()
    for tags in df["tags"].dropna():
        # tags may come back as a list already, or as a string representation
        if isinstance(tags, str):
            tags = tags.strip("{}").split(",")
        for tag in tags:
            tag = str(tag).strip().strip('"').lower()
            if tag:
                counter[tag] += 1

    freq_df = pd.DataFrame(counter.items(), columns=["skill", "job_count"])
    freq_df = freq_df.sort_values("job_count", ascending=False).reset_index(drop=True)
    freq_df["computed_at"] = datetime.now(timezone.utc)
    return freq_df


def compute_role_freshness(df: pd.DataFrame) -> pd.DataFrame:
    """
    Use scraped_at (first seen) and last_seen_at (most recent scrape that
    still found this job) to classify each posting's status:
      - active: last_seen_at is recent (within the last scrape cycle)
      - stale: hasn't reappeared in a while, likely filled/removed
    """
    now = pd.Timestamp.now(tz="UTC")
    df = df.copy()
    df["scraped_at"] = pd.to_datetime(df["scraped_at"], utc=True)
    df["last_seen_at"] = pd.to_datetime(df["last_seen_at"], utc=True)
    df["days_since_last_seen"] = (now - df["last_seen_at"]).dt.total_seconds() / 86400
    df["days_live"] = (df["last_seen_at"] - df["scraped_at"]).dt.total_seconds() / 86400

    def classify(days_since_last_seen):
        if days_since_last_seen <= 1:
            return "active"
        elif days_since_last_seen <= 7:
            return "cooling"
        else:
            return "stale"

    df["status"] = df["days_since_last_seen"].apply(classify)

    freshness_df = df[[
        "job_id", "title", "company", "source",
        "scraped_at", "last_seen_at", "days_live", "status"
    ]].copy()
    freshness_df["computed_at"] = datetime.now(timezone.utc)
    return freshness_df


def write_results(skill_df: pd.DataFrame, freshness_df: pd.DataFrame):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS analysis_skill_frequency (
                skill TEXT,
                job_count INTEGER,
                computed_at TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS analysis_role_freshness (
                job_id TEXT,
                title TEXT,
                company TEXT,
                source TEXT,
                scraped_at TIMESTAMP,
                last_seen_at TIMESTAMP,
                days_live FLOAT,
                status TEXT,
                computed_at TIMESTAMP
            )
        """))

    skill_df.to_sql("analysis_skill_frequency", engine, if_exists="append", index=False)
    freshness_df.to_sql("analysis_role_freshness", engine, if_exists="append", index=False)
    print(f"Wrote {len(skill_df)} skill rows and {len(freshness_df)} freshness rows")


def main():
    df = load_raw_jobs()
    if df.empty:
        print("No data in raw_jobs yet — run the n8n pipeline first.")
        return

    skill_df = compute_skill_frequency(df)
    freshness_df = compute_role_freshness(df)

    print("\nTop 10 skills right now:")
    print(skill_df.head(10).to_string(index=False))

    print("\nRole status breakdown:")
    print(freshness_df["status"].value_counts())

    write_results(skill_df, freshness_df)


if __name__ == "__main__":
    main()
