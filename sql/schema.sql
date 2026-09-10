-- Job Market Pipeline — Database Schema (Supabase / Postgres)
-- Run this in Supabase's SQL Editor to set up the required tables.

-- Raw scraped job postings, deduplicated by job_id via upsert from n8n.
CREATE TABLE IF NOT EXISTS raw_jobs (
    job_id TEXT UNIQUE NOT NULL,
    title TEXT,
    company TEXT,
    location TEXT,
    remote BOOLEAN,
    tags TEXT[],
    url TEXT,
    posted_date TIMESTAMP,
    source TEXT,
    scraped_at TIMESTAMP DEFAULT now(),   -- first time this job_id was seen
    last_seen_at TIMESTAMP DEFAULT now()  -- most recent scrape that still found it
);

-- Skill/tag frequency snapshots, written daily by analyze_jobs.py.
CREATE TABLE IF NOT EXISTS analysis_skill_frequency (
    skill TEXT,
    job_count INTEGER,
    computed_at TIMESTAMP
);

-- Role freshness snapshots (active / cooling / stale), written daily by analyze_jobs.py.
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
);

-- Latest AI-generated market report. generate_report.py keeps only the single
-- most recent row here, deleting older ones after each new insert.
CREATE TABLE IF NOT EXISTS reports (
    id SERIAL PRIMARY KEY,
    report_text TEXT,
    generated_at TIMESTAMP
);