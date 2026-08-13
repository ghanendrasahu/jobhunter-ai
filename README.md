# JobHunter AI

**Upload a resume PDF — get matched jobs and automated applications powered by AI.**

JobHunter AI is a resume-driven job-search automation toolkit for the Indian job market. It
extracts text from a PDF resume, uses an LLM to generate a search query, discovers jobs from
multiple sources (Playwright scrapers, Adzuna/Jooble APIs, and direct portal links), scores each
job against your resume, records applications, and tracks everything in a dashboard.

The pipeline is orchestrated as a **LangGraph state machine**, exposed through a **Streamlit
dashboard**, a **FastAPI REST endpoint**, and a **CLI**.

---

## Features

- 📄 **PDF resume parsing** (`pypdf`)
- 🤖 **AI search-query generation** via LangChain + OpenAI (with keyword fallback)
- 🔍 **Multi-source job discovery** — Indeed, LinkedIn, Naukri (Playwright), Adzuna & Jooble (APIs), plus one-click portal links
- 🎯 **Resume–job match scoring** with matched/missing skill breakdown
- 📝 **Application tracking** with duplicate detection and history export (CSV)
- 📊 **Analytics dashboard** (Streamlit + Plotly)
- 🔐 **Optional REST API** with API-key auth and rate limiting
- 📧 **Email notifications** after each pipeline run (optional)
- 🤖 **Semi-autonomous apply agent** — logs into Naukri/Indeed, scores jobs with Groq, and auto-fills application forms (human-in-the-loop or full-auto)

---

## Architecture

```
                ┌───────────────────────────┐
                │   Entry points            │
                │  python -m jobhunter      │  CLI
                │  jobhunter-web            │  Streamlit dashboard
                │  uvicorn jobhunter.api:app│  REST API
                └────────────┬──────────────┘
                             ▼
                ┌───────────────────────────┐
                │   jobhunter.agent         │  LangGraph pipeline
                │  extract → query → search → apply
                └──────┬────────────────────┘
                       │
        ┌──────────────┼───────────────────────────┐
        ▼              ▼                           ▼
┌──────────────┐ ┌──────────────┐        ┌──────────────────┐
│ domains/     │ │ domains/search/*│      │ storage/history  │
│ resume       │ │ portals      │        │ services/analytics
│ matching     │ │ scrapers     │        │ services/notifications
└──────────────┘ │ api_sources  │        └──────────────────┘
                 │ engine       │
                 └──────────────┘
```

### Pipeline steps

1. **extract_resume** — parse the PDF into plain text (`domains/resume.py`)
2. **generate_query** — ask the LLM for a concise search query; fall back to keyword extraction
3. **find_jobs** — search scrapers + APIs + portal links, then score each job against the resume
4. **apply_jobs** — record applications (portal links open in the browser), send a summary email

Each node is wrapped in `try/except` and sets an `error` field on failure, which short-circuits
the downstream nodes.

---

## Project structure

```
JobHunter AI/
├── src/
│   └── jobhunter/             # Main package (src layout)
│       ├── __init__.py
│       ├── __main__.py        # python -m jobhunter (CLI)
│       ├── config.py          # pydantic-settings (env/.env)
│       ├── agent.py           # LangGraph pipeline + run_job_hunter()
│       ├── cli.py             # CLI entry point
│       ├── web.py             # Streamlit launcher
│       ├── scheduler.py       # scheduled/background runner
│       ├── domains/
│       │   ├── resume.py      # PDF text extraction
│       │   ├── matching.py    # job/resume match scoring
│       │   └── search/
│       │       ├── portals.py # portal link generation
│       │       ├── scrapers.py# Playwright scrapers (Indeed/LinkedIn/Naukri)
│       │       ├── api_sources.py  # Adzuna, Jooble & JSearch APIs
│       │       └── engine.py  # search orchestration + dedupe
│       ├── storage/
│       │   └── history.py     # resume storage + application history + CSV
│       ├── services/
│       │   ├── analytics.py   # dashboard aggregation
│       │   └── notifications.py  # SMTP email alerts
│       ├── automation/        # semi-autonomous apply agent
│       │   ├── browser.py, evaluator.py, form_filler.py,
│       │   ├── profile.py, strategies.py, apply_agent.py, apply.py
│       ├── api/
│       │   └── server.py      # FastAPI app factory
│       └── ui/
│           ├── dashboard.py   # Streamlit app shell + sidebar
│           ├── components.py  # shared rendering (CSS, job cards, results)
│           └── views.py       # page views (search, auto-apply, analytics, …)
├── tests/                     # pytest suite
│   ├── conftest.py            # fixtures + minimal PDF generator
│   ├── test_pdf.py
│   ├── test_matcher.py
│   ├── test_history.py
│   ├── test_search.py
│   ├── test_agent.py
│   ├── test_api.py
│   ├── test_scheduler.py
│   └── test_automation.py
├── pyproject.toml             # deps, console scripts, pytest/ruff/mypy config
├── requirements.txt           # flat dependency pins
├── docker-compose.yml         # Containerized Streamlit service
├── Dockerfile
├── .github/workflows/ci.yml   # lint + type-check + tests
├── .env.example
└── .gitignore
```

---

## Quick start

### Prerequisites

- Python 3.11+
- (Optional) An [OpenAI API key](https://platform.openai.com/api-keys) for AI query generation
- (Optional) Playwright browser: `python -m playwright install chromium`

### Setup

```bash
# Install runtime deps, then install the package (provides the console scripts)
pip install -r requirements.txt
pip install -e .

# Optional: Playwright browser for scraping
python -m playwright install chromium

# Configure environment
cp .env.example .env
# add OPENAI_API_KEY and optional job-API / SMTP keys
```

### Run the CLI

```bash
python -m jobhunter                         # interactive prompt
python -m jobhunter /path/to/resume.pdf     # run a specific PDF
python -m jobhunter --schedule --query "Python Developer" --interval 360  # scheduled loop
```

### Run the Streamlit dashboard

```bash
jobhunter-web
# or
python -m jobhunter.web
```

### Run the FastAPI server

```bash
uvicorn jobhunter.api:app --reload --port 8000
curl http://localhost:8000/health
curl -X POST http://localhost:8000/upload_resume -F "file=@/path/to/resume.pdf"
```

### Docker

```bash
docker build -t jobhunter-ai .
docker run -p 8501:8501 jobhunter-ai

# or use docker compose (mounts history/ and resumes/ as volumes)
docker compose up --build
```

### Run the Auto-Apply agent

```bash
# CLI (human mode = pre-fill, you click submit)
python -m jobhunter.automation.apply --query "Python Developer" --resume resume.pdf

# Full-auto mode (agent clicks submit)
python -m jobhunter.automation.apply -q "Data Analyst" -r resume.pdf --mode auto --portals naukri indeed --max 3
```

Or use the **🤖 Auto Apply** page in the Streamlit dashboard. The agent:
1. Reuses a persistent logged-in browser session (`data/browser_state/`), so you log into Naukri/Indeed once.
2. Searches each portal, then has Groq score every job against your resume (keyword fallback offline).
3. Opens the apply form and pre-fills it from your resume profile.
4. In **human** mode you finish + submit (needed for CAPTCHAs / multi-step ATS forms); in **auto** mode it submits for you.
5. Records every application to your history (visible on the Dashboard).

> **Two ways to use your account (both give you real confirmation emails):**
> 1. **`.env` credentials** — set `NAUKRI_EMAIL/NAUKRI_PASSWORD` (and/or
>    `INDEED_EMAIL/INDEED_PASSWORD`). The agent logs in through the portal's own
>    form (no Google sign-in, so Google never blocks it), applies from your
>    account, and confirmation emails land in the email on that account.
> 2. **Default-Chrome sessions** — the agent copies a minimal slice of your Chrome
>    profile and reuses all existing logins automatically.
>
> Install the browser engine once: `python -m playwright install chromium`
> Portals block automation aggressively. Start in `human` mode and keep volume low to avoid account bans; a company confirmation email only arrives after a *real* submission.

---

## Configuration

| Environment variable     | Required | Description                                      |
|--------------------------|----------|--------------------------------------------------|
| `OPENAI_API_KEY`         | No*      | Enables LLM query generation (keyword fallback otherwise) |
| `OPENAI_MODEL`           | No       | Chat model used for query generation (`gpt-4o-mini`) |
| `GROQ_API_KEY`           | No*      | Prefer Groq over OpenAI when set (OpenAI-compatible, free tier) |
| `GROQ_MODEL`             | No       | Groq model used when `GROQ_API_KEY` is set (`llama-3.3-70b-versatile`) |
| `GROQ_BASE_URL`          | No       | Groq endpoint (defaults to `https://api.groq.com/openai/v1`) |
| `ADZUNA_APP_ID`          | No       | Adzuna API app ID (live job search)              |
| `ADZUNA_API_KEY`         | No       | Adzuna API key                                   |
| `JOOBLE_API_KEY`         | No       | Jooble API key                                   |
| `SMTP_HOST` / `SMTP_PORT`| No       | SMTP settings for email alerts                   |
| `SMTP_USER` / `SMTP_PASS`| No       | SMTP credentials (use an app password for Gmail) |
| `NOTIFICATION_EMAIL`     | No       | Recipient for pipeline reports                   |
| `JOBHUNTER_API_KEY`      | No       | If set, REST clients must send `X-API-Key` header|
| `API_RATE_LIMIT`         | No       | FastAPI rate limit (default `20/minute`)         |
| `MAX_FILE_SIZE_MB`       | No       | Max PDF upload size (default `10`)               |
| `NAUKRI_EMAIL` / `NAUKRI_PASSWORD` | No | Naukri login for the apply agent (optional — manual login in browser window) |
| `INDEED_EMAIL` / `INDEED_PASSWORD` | No | Indeed login for the apply agent (optional — manual login in browser window) |
| `AUTO_APPLY_MODE`        | No       | `human` (pre-fill, user submits), `auto`, `off` (default `human`) |
| `MAX_APPLICATIONS_PER_RUN` | No     | Cap per run (default `5`)                        |
| `HEADLESS_BROWSER`       | No       | Run the browser hidden (default `false`)         |
| `BROWSER_CHANNEL`        | No       | `chrome` (installed Chrome, default) or `chromium` (bundled) |
| `BROWSER_USE_DEFAULT_PROFILE` | No | Reuse your default Chrome logins via an auto-refreshed minimal profile copy (default `true`) |
| `BROWSER_USER_DATA_DIR`  | No       | Explicit Chrome 'User Data' dir (auto-detected when empty) |
| `MANUAL_LOGIN_TIMEOUT`   | No       | Seconds to wait for manual login (default `180`) |
| `FRESHER_ONLY`           | No       | Fresher-only mode: augments the query, skips senior roles (default `true`) |
| `MAX_EXPERIENCE_YEARS`   | No       | Jobs requiring more years than this are skipped (default `2`) |

\* *The pipeline works fully without an OpenAI key — query generation falls back to keyword extraction.*

---

## API reference

### `POST /upload_resume`

Upload a PDF resume to run the pipeline.

- **Request:** `multipart/form-data` with a `file` field (`.pdf`)
- **Size limit:** 10 MB (configurable via `MAX_FILE_SIZE_MB`)
- **Rate limit:** 20 requests/minute (configurable)
- **Auth:** optional — set `JOBHUNTER_API_KEY` to require the `X-API-Key` header
- **Response:** JSON with `resume_text`, `search_query`, `jobs`, `applications`, `error`

### `GET /health`

Liveness probe — returns `{"status": "ok", "version": "3.0.0"}`.

---

## Running tests

```bash
pip install -e ".[dev]"
python -m pytest
# with coverage:
python -m pytest --cov=jobhunter --cov-report=term-missing
```

Test coverage includes PDF extraction, match scoring, history/resume management, search
orchestration & deduplication, the full LangGraph pipeline, and the REST API (validation, auth,
rate limiting).

---

## Extending

- **Add a job API:** create a `search_*_jobs` function in `domains/search/api_sources.py` and call it from `domains/search/engine.py`
- **Add a scraper:** follow the existing Playwright patterns in `domains/search/scrapers.py` and register it in `domains/search/engine.py`
- **Use a different LLM:** swap the `ChatOpenAI` in `agent.py` for any LangChain chat model
- **Real ATS submission:** replace `apply_to_job` in `storage/history.py` with an HTTP/Playwright submitter

---

## License

MIT
