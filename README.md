\# Remote Job Market Pipeline



An end-to-end data pipeline that scrapes remote job postings from three sources, stores and deduplicates them, computes daily analytics, generates an AI-written market summary, and displays everything in an interactive dashboard — running fully unattended on a $0/month stack (aside from a small AWS EC2 instance).



\*\*Live dashboard:\*\* https://job-market-pipeliine.streamlit.app/



!\[Workflow](n8n/workflow-screenshot.png)



\## What it does



Every 24 hours, the pipeline:

1\. \*\*Scrapes\*\* job postings from \[RemoteOK](https://remoteok.com), \[Arbeitnow](https://arbeitnow.com), and \[Jobicy](https://jobicy.com)

2\. \*\*Deduplicates\*\* them against previously seen postings (via `job\_id` upsert) and tracks how long each posting stays live

3\. \*\*Computes\*\* skill/tag frequency and a "freshness" status (active / cooling / stale) for every posting

4\. \*\*Generates\*\* a plain-English market summary using an LLM (Groq / Llama)

5\. \*\*Displays\*\* all of it in a two-page Streamlit dashboard with cross-filtering charts



\## Architecture



```

n8n (self-hosted, AWS EC2)

&#x20; ├─ Schedule Trigger (daily)

&#x20; ├─ 3× HTTP Request → Split Out → Edit Fields   (one branch per source)

&#x20; ├─ Merge (append)

&#x20; └─ Postgres upsert → Supabase



cron (same EC2 instance)

&#x20; ├─ analyze\_jobs.py     → skill frequency + role freshness → Supabase

&#x20; └─ generate\_report.py  → Groq API → AI summary → Supabase



Streamlit (Community Cloud)

&#x20; ├─ app.py         → overview, filters, time-window explorer, cross-filter charts

&#x20; └─ pages/1\_Report.py → latest AI-generated report

```



| Layer | Tool | Why |

|---|---|---|

| Orchestration | n8n (self-hosted) | Free, visual, handles parallel API calls cleanly |

| Hosting | AWS EC2 (t2/t3.micro) | Free-tier eligible; see \[tradeoffs](#tradeoffs-and-decisions) below |

| Database | Supabase (Postgres) | Free tier, standard SQL, connection pooler works well for scheduled/serverless-style access |

| Analysis | Python (pandas, SQLAlchemy) | Runs on a daily cron job on the same EC2 instance |

| AI reporting | Groq API (Llama / gpt-oss) | Free tier, fast, avoids running an LLM locally on a 1GB-RAM instance |

| Dashboard | Streamlit + Plotly | Free hosting on Community Cloud, native Python, good enough interactivity for this scope |



\## Setup



1\. \*\*Database:\*\* run `sql/schema.sql` in your Supabase SQL Editor.

2\. \*\*n8n:\*\* import `n8n/job-scraper-pipeline.json`, add your Supabase Postgres credential (use the \*\*Transaction Pooler\*\* connection details, not the direct connection — see \[tradeoffs](#tradeoffs-and-decisions)), and activate the workflow.

3\. \*\*Python scripts:\*\* on your server, `pip install -r python/requirements.txt`, then set these environment variables (a crontab-level `SHELL=/bin/bash` plus inline variables — not `.bashrc` — see notes below):

&#x20;  ```

&#x20;  SUPABASE\_DB\_HOST, SUPABASE\_DB\_USER, SUPABASE\_DB\_PASSWORD, GROQ\_API\_KEY

&#x20;  ```

&#x20;  Schedule `analyze\_jobs.py` and `generate\_report.py` via cron, a few minutes apart.

4\. \*\*Dashboard:\*\* `pip install -r streamlit\_app/requirements.txt`, set the same Supabase variables (as Streamlit secrets when deployed, env vars locally), then `streamlit run streamlit\_app/app.py`.



\## Tradeoffs and decisions



A few choices made deliberately, worth knowing if you're reviewing or extending this:



\- \*\*AWS over Oracle Cloud Free Tier.\*\* Oracle's forever-free tier looked attractive on paper but requires card verification with strict card-type rules, and has known capacity/availability issues in some regions. AWS, which I already had access to, was more reliable in practice.

\- \*\*Hosted LLM (Groq) over local Ollama.\*\* The EC2 instance has only \~1GB RAM — barely enough for n8n itself. Running a local LLM on top of that caused repeated out-of-memory crashes (see below). A free hosted API removed that failure mode entirely.

\- \*\*Supabase's Transaction Pooler over Direct Connection.\*\* Direct connections default to IPv6, which the EC2 instance couldn't reach. The pooler also fits the access pattern better anyway — short, scheduled connections rather than one long-lived one.

\- \*\*Single report row instead of full history.\*\* The `reports` table keeps only the most recent AI-generated summary, deleting older ones on each run, to keep the dashboard focused on "what's true right now" rather than an ever-growing archive.

\- \*\*Google Sheets export dropped.\*\* The original plan included a parallel Google Sheets export for raw data. Since Postgres already serves as the single source of truth and queryable store, this was cut to avoid unnecessary OAuth setup and an extra point of failure for no real analytical benefit.



\## Problems hit and fixed



This project surfaced a number of real operational issues, not just "happy path" development:



\- \*\*Out-of-memory crash loops.\*\* n8n's Node process was silently killed by the Linux OOM killer on the 1GB-RAM instance. Diagnosed via `dmesg | grep -i "killed process"`, fixed with a swap file sized to balance memory headroom against limited disk space.

\- \*\*Disk exhaustion, repeatedly.\*\* An 8GB root volume filled up multiple times from Docker images, n8n's execution history, and package caches. Fixed short-term via `apt clean`, `docker system prune`, and periodic `VACUUM` on n8n's SQLite database; fixed structurally by enabling `EXECUTIONS\_DATA\_PRUNE` and reducing the scrape schedule from every 6 hours to daily.

\- \*\*Cron silently failing due to environment variables.\*\* Cron jobs calling `source \~/.bashrc` failed silently because non-interactive shells exit `.bashrc` early. Fixed by declaring environment variables directly in the crontab instead.

\- \*\*n8n's schedule not firing despite being "Published."\*\* A newer n8n version replaced the classic Active/Inactive toggle with a Publish/Unpublish model; edits made after publishing didn't reliably re-register the schedule. Fixed by explicitly unpublishing and republishing after any settings change.

\- \*\*Deprecated LLM model.\*\* The originally chosen Groq model (`llama-3.1-8b-instant`) was deprecated mid-project, returning HTTP 404. Swapped to Groq's current recommended model with no other code changes needed.

\- \*\*Stale freshness tracking.\*\* The `last\_seen\_at` column, meant to track whether a posting is still live, was never actually updating on repeat scrapes — the upsert only set it via a database default on `INSERT`, which doesn't fire on `UPDATE`. Fixed by explicitly setting `last\_seen\_at = NOW()` in the upsert's column list.

\- \*\*Single-source outages breaking the whole run.\*\* Arbeitnow returned an HTTP 521 (origin server down) on one occasion, which failed the entire n8n execution and blocked RemoteOK/Jobicy from saving data too. Fixed by enabling "Continue On Fail" on each source's HTTP Request node, so one source's outage no longer blocks the others.



\## Repo structure



```

├── n8n/                    # exported workflow + screenshot

├── python/                 # analysis + LLM report generation, run via cron

├── sql/                    # database schema

└── streamlit\_app/          # dashboard (deploy this folder's app.py to Streamlit Cloud)

```

