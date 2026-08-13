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
                │  run.py │ app.py │ streamlit_app.py
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
│ core/pdf     │ │ search/*     │        │ core/history     │
│ core/matcher │ │ portals      │        │ core/analytics   │
└──────────────┘ │ scrapers     │        │ notifications    │
                 │ api_sources  │        └──────────────────┘
                 │ engine       │
                 └──────────────┘
```

### Pipeline steps

1. **extract_resume** — parse the PDF into plain text (`core/pdf.py`)
2. **generate_query** — ask the LLM for a concise search query; fall back to keyword extraction
3. **find_jobs** — search scrapers + APIs + portal links, then score each job against the resume
4. **apply_jobs** — record applications (portal links open in the browser), send a summary email

Each node is wrapped in `try/except` and sets an `error` field on failure, which short-circuits
the downstream nodes.

---

## Project structure

```
JobHunter AI/
├── jobhunter/                 # Main package
│   ├── __init__.py
│   ├── config.py              # pydantic-settings (env/.env)
│   ├── agent.py               # LangGraph pipeline + run_job_hunter()
│   ├── notifications.py       # SMTP email alerts
│   ├── core/
│   │   ├── pdf.py             # PDF text extraction
│   │   ├── matcher.py         # job/resume match scoring
│   │   ├── history.py         # resume storage + application history + CSV
│   │   └── analytics.py       # dashboard aggregation
│   ├── search/
│   │   ├── portals.py         # portal link generation
│   │   ├── scrapers.py        # Playwright scrapers (Indeed/LinkedIn/Naukri)
│   │   ├── api_sources.py     # Adzuna & Jooble APIs
│   │   └── engine.py          # search orchestration + dedupe
│   ├── api/
│   │   └── server.py          # FastAPI app factory
│   └── ui/
│       └── dashboard.py       # Streamlit dashboard
├── tests/                     # pytest suite
│   ├── conftest.py            # fixtures + minimal PDF generator
│   ├── test_pdf.py
│   ├── test_matcher.py
│   ├── test_history.py
│   ├── test_search.py
│   ├── test_agent.py
│   └── test_api.py
├── app.py                     # FastAPI entry point (uvicorn app:app)
├── streamlit_app.py           # Streamlit entry point
├── main.py                    # Streamlit launcher alias (python main.py)
├── run.py                     # CLI entry point
├── requirements.txt           # Full install (core + extras)
├── requirements-core.txt      # Core-only deps (CLI + pipeline)
├── requirements-dev.txt       # + test tooling (pytest)
├── setup.bat                  # Windows one-click setup
├── docker-compose.yml         # Containerized Streamlit service
├── pytest.ini
├── Dockerfile
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

**Windows:** double-click `setup.bat` (installs deps, Playwright, and creates `.env`).

**Manual:**

```bash
pip install -r requirements.txt        # or requirements-core.txt for CLI/pipeline only

# Optional: Playwright browser for scraping
python -m playwright install chromium

# Configure environment
cp .env.example .env
# add OPENAI_API_KEY and optional job-API / SMTP keys
```

### Run the CLI

```bash
python run.py                         # interactive prompt
python run.py /path/to/resume.pdf     # run a specific PDF
```

### Run the Streamlit dashboard

```bash
streamlit run streamlit_app.py
# or
python main.py
```

### Run the FastAPI server

```bash
uvicorn app:app --reload --port 8000
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
| `NAUKRI_EMAIL` / `NAUKRI_PASSWORD` | No | Naukri login for the apply agent          |
| `INDEED_EMAIL` / `INDEED_PASSWORD` | No | Indeed login for the apply agent          |
| `AUTO_APPLY_MODE`        | No       | `human` (pre-fill, user submits), `auto`, `off` (default `human`) |
| `MAX_APPLICATIONS_PER_RUN` | No     | Cap per run (default `5`)                        |
| `HEADLESS_BROWSER`       | No       | Run the browser hidden (default `false`)         |

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
pip install -r requirements-dev.txt
python -m pytest
# with coverage:
python -m pytest --cov=jobhunter --cov-report=term-missing
```

Test coverage includes PDF extraction, match scoring, history/resume management, search
orchestration & deduplication, the full LangGraph pipeline, and the REST API (validation, auth,
rate limiting).

---

## Extending

- **Add a job API:** create a `search_*_jobs` function in `search/api_sources.py` and call it from `search/engine.py`
- **Add a scraper:** follow the existing Playwright patterns in `search/scrapers.py` and register it in `search/engine.py`
- **Use a different LLM:** swap the `ChatOpenAI` in `agent.py` for any LangChain chat model
- **Real ATS submission:** replace `apply_to_job` in `core/history.py` with an HTTP/Playwright submitter

---

## License

MIT
