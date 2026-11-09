# JobHunter AI

**Upload a resume PDF — get matched jobs and automated applications powered by AI.**

JobHunter AI is a resume-driven job-search automation toolkit for the Indian job market. It
extracts text from a PDF resume, uses an LLM to generate a search query, discovers jobs from
multiple sources (Playwright scrapers, Adzuna/Jooble APIs, and direct portal links), scores each
job against your resume, records applications, and tracks everything in a dashboard.

The pipeline is orchestrated as a **LangGraph state machine**, exposed through a **Streamlit
dashboard**, a **FastAPI REST endpoint**, and a **CLI**.

> **Live demo:** https://jobhunter-ai-h73m.onrender.com
>
> Free-tier hosting: the first load after idle can take 30-60 seconds.

---

## Features

- 📄 **PDF resume parsing** (`pypdf`)
- 🤖 **AI search-query generation** via LangChain + OpenAI (with keyword fallback)
- 🛡️ **Deterministic eligibility (PH5) before relevance ranking (PH6)** — a hard gate no LLM can override
- 🔍 **Multi-source job discovery** — Indeed, LinkedIn, Naukri (Playwright), Adzuna & Jooble (APIs), plus one-click portal links
- 🎯 **Resume–job match scoring** with matched/missing skill breakdown
- 📝 **Application tracking** with duplicate detection and history export (CSV)
- 📊 **Analytics dashboard** (Streamlit + Plotly) with run metrics and an errors & warnings view
- 🔐 **Optional REST API** with API-key auth and rate limiting
- 📧 **Email notifications** after each pipeline run (optional)
- 🤖 **Semi-autonomous apply agent** — logs into Naukri/Indeed, scores jobs with Groq, and auto-fills application forms (human-in-the-loop or full-auto)
- 🎯 **Priority role discovery** — suggests AI/ML/Data/Analyst roles from your resume, lets you pick the ones to hunt, and ranks every job by recency, fresher-fit, salary, remote/WFH, and role tier
- 🔁 **Continuous auto-apply** — runs batch-after-batch on a cooldown, rotating your priority roles, deduping against applied history, until you press Stop

---

## Architecture

```text
                ┌───────────────────────────┐
                │   Entry points            │
                │  python -m jobhunter      │  CLI
                │  jobhunter-web            │  Streamlit dashboard
                │  uvicorn jobhunter.api:app│  REST API
                └────────────┬──────────────┘
                             ▼
                ┌────────────┬──────────────┐
                │   jobhunter.agent         │  LangGraph pipeline
                │  extract → query →        │
                │  discover → PH5 → PH6    │
                │  → apply                  │
                └──────┬────────────────────┘
                       │
        ┌──────────────┼───────────────────────────┐
        ▼              ▼                           ▼
┌──────────────┐ ┌──────────────┐        ┌──────────────────┐
│ domains/     │ │ domains/search/*│      │ storage/         │
│ resume       │ │ portals      │        │ history (SQLite) │
│ eligibility  │ │ scrapers     │        │ profiles         │
│ (PH5 gate)   │ │ api_sources  │        │ run_state        │
│ scoring      │ │ engine       │        │ qa memory, settings│
│ (PH6 ranking)│ └──────────────┘        └──────────────────┘
│ jobs/candidate│
└──────────────┘
```

### Pipeline steps

1. **extract_resume** — parse the PDF into plain text (`domains/resume.py`)
2. **generate_query** — ask the LLM for a concise search query; fall back to keyword extraction
3. **find_jobs** — portal links + registered sources + optional job APIs, deduplicated
4. **build_candidate** — Candidate knowledge (role family, skills, seniority, experience)
5. **assess_eligibility** — **PH5 HARD GATE**: deterministic eligibility per job (LLM can never override it)
6. **score_jobs** — **PH6 relevance ranking** (deterministic + optional LLM refinement); only eligible jobs are scored
7. **apply_jobs** — consume the PH6-ranked eligible jobs: `off` (default) records/opens; opt-in `human`/`auto` applies via the apply agent — capped, deduplicated, verified

Safety invariants (enforced in code, see `docs/safety.md`):

- PH5 eligibility runs before PH6; failing jobs are dropped before scoring.
- LLM scores never override eligibility; unknown knowledge goes to `needs_review`.
- Discovery-only sources and unsupported portals never auto-apply.
- Auto-apply runs only in the dedicated authenticated browser; a failed browser refuses the run.
- Nothing is recorded as applied without post-click verification; everything is recorded in `history/history.db`.

---

## Project structure

```text
JobHunter AI/
├── src/
│   └── jobhunter/             # Main package (src layout)
│       ├── __init__.py        # __version__ (single source of truth)
│       ├── __main__.py        # python -m jobhunter
│       ├── config.py          # pydantic-settings (env/.env) + validate_config
│       ├── agent.py           # LangGraph pipeline (extract→query→discover→PH5→PH6→apply)
│       ├── cli.py             # CLI entry point
│       ├── web.py             # Streamlit launcher
│       ├── scheduler.py       # scheduled/background runner
│       ├── logging_setup.py   # text or single-line JSON logs
│       ├── domains/
│       │   ├── jobs.py        # normalized Job + dedupe fingerprint
│       │   ├── eligibility.py # PH5 hard gate (deterministic)
│       │   ├── scoring.py     # PH6 relevance ranking
│       │   ├── candidate.py   # Candidate knowledge (persisted)
│       │   ├── resume.py      # PDF text extraction
│       │   └── search/        # portals / scrapers / api_sources / engine / sources/
│       ├── storage/           # history, settings, profiles, qa, run_state, schema
│       ├── services/          # analytics, notifications, retry
│       ├── automation/        # apply agent: browser, strategies, form_filler,
│       │                      # evaluator, apply_agent, apply_contract (routing gate)
│       ├── api/server.py      # FastAPI app factory (+ /ready readiness probe)
│       └── ui/                # dashboard, views, control_center, state, components, design
├── tests/                     # pytest suite (550+ tests; see pyproject.toml)
├── docs/                      # configuration / browser-setup / safety guides
├── run.ps1                    # Windows launcher (dashboard default; -Menu utility menu)
├── pyproject.toml             # deps, console scripts, pytest/ruff/mypy config
├── uv.lock                    # locked dependency resolution (uv)
├── Dockerfile, docker-compose.yml
├── .env.example               # every setting, documented
└── .github/workflows/ci.yml   # lint + type-check + tests (coverage gate ≥ 60%)
```

---

## Quick start

### Prerequisites

- Python 3.11 (only 3.11.x is supported)
- (Optional) An [OpenAI API key](https://platform.openai.com/api-keys) for AI query generation
- (Optional) Playwright browser: `python -m playwright install chromium`

### One-command quick start (Windows)

```powershell
.\run.ps1                 # sync deps + open the dashboard on http://localhost:8501
.\run.ps1 -Service api    # or the FastAPI server on :8000
.\run.ps1 -Service cli    # or the interactive CLI
.\run.ps1 -Menu           # utility menu: tests + coverage, ruff, mypy, browser install
```

### Setup

```bash
# Option A — uv (fast, reproducible; locks via uv.lock)
uv sync --locked                      # installs runtime + dev deps
uv run playwright install chromium    # Optional: browser for scraping

# Option B — pip
pip install -r requirements.txt       # runtime deps
pip install -r requirements-dev.txt   # dev deps (tests, lint, mypy)
pip install -e .                      # provides the console scripts
python -m playwright install chromium # Optional: browser for scraping

# Configure environment
cp .env.example .env
# add OPENAI_API_KEY and optional job-API / SMTP keys
```

### First run (dashboard, 5 minutes)

1. `uv sync --locked`
2. `cp .env.example .env` — works empty; add keys only if you want them
3. `uv run jobhunter-web` and open http://localhost:8501
4. Upload your resume PDF on **Job Search** → **Run job search**
5. Review results (eligibility → relevance → applications). By default nothing is auto-submitted — `AUTO_APPLY_MODE=human` is the default and leaves the final click to you.

For the Auto Apply page you also need the dedicated Chrome window — see `docs/browser-setup.md`. Safety model, what never happens, and known limitations: `docs/safety.md`. The full configuration reference: `docs/configuration.md`.

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

> The container runs as a non-root user, exposes a `/` healthcheck on port 8501,
> and mounts `./data` so your browser session survives restarts.

### Settings persistence

Dashboard settings (portal credentials, auto-apply mode, application cap, SMTP) saved on the
**⚙️ Settings** page are stored in a `settings` table inside `history/history.db` and override
environment variables. Environment variables still win for anything not exposed in the UI.

When `JOBHUNTER_APP_SECRET` is set, credential values stored there (portal passwords, SMTP
password) are **encrypted at rest** (Fernet, `enc:v1:` prefix). Previously saved plaintext
values keep loading and re-encrypt the next time you save them.

---

## Safety & operations

The full behavior contract, outcome semantics, crash-safety guarantees and known limitations are
documented in [`docs/safety.md`](docs/safety.md). Browser setup and the login workflow are in
[`docs/browser-setup.md`](docs/browser-setup.md). Highlights:

- **PH5 eligibility gate** runs before any scoring; PH5 can never be overridden (not by an LLM, not by configuration).
- **Discovery-only sources and unsupported portals never auto-apply.**
- **No unsafe fallback**: the auto-apply path requires the dedicated authenticated browser; it is refused otherwise.
- **Verified outcomes only**: `submitted` is recorded only after post-click verification; crashes never produce duplicate applications.
- **Sensitive fields are never auto-filled** (password, OTP, CAPTCHA, legal/demographic questions) — the agent always stops and asks you.
- Every application is explainable: eligibility → relevance → route → outcome.


- **API auth** — optional `X-API-Key` requirement via `JOBHUNTER_API_KEY`
- **Rate limiting** — slowapi, default `20/minute` (`API_RATE_LIMIT`)
- **Upload hardening** — PDF-only (extension + MIME) with a size cap (`MAX_FILE_SIZE_MB`)
- **CORS** — explicit origins via `CORS_ORIGINS`; empty = same-origin only; `*` never carries credentials
- **Encrypted credentials at rest** — persisted portal/SMTP passwords with `JOBHUNTER_APP_SECRET`
- **Probes** — `GET /health` (liveness) and `GET /ready` (readiness; 503 with reasons if local state is unusable)
- **JSON logging** — `LOG_JSON=true` emits single-line JSON records (`ts`, `level`, `logger`, `message`)
- **Gated CI** — ruff + mypy + pytest with a 60% coverage floor before any commit lands

### Run the Auto-Apply agent

```bash
# CLI (human mode = pre-fill, you click submit)
python -m jobhunter.automation.apply --query "Python Developer" --resume resume.pdf

# Full-auto mode (agent clicks submit)
python -m jobhunter.automation.apply -q "Data Analyst" -r resume.pdf --mode auto --portals naukri indeed --max 3

# Continuous mode: keep running until Ctrl-C, rotating priority roles on a cooldown
python -m jobhunter.automation.apply -r resume.pdf --mode auto --continuous --cooldown 300 --batch 10
```

Or use the **🤖 Auto Apply** page in the Streamlit dashboard (a 3-step wizard):

1. **Profile** — paste or generate a profile from your resume (stored for reuse).
2. **Priority roles** — the app suggests AI/ML/Data/Analyst roles from your resume across
   three tiers (⭐ Priority / Software / Other); pick the ones you want to hunt.
3. **Run** — set the apply mode, portals, batch size, cooldown and whether to keep going until
   you press **Stop**. A live console shows each job being scored, filled and submitted.

The agent:

1. Reuses a persistent logged-in browser session (`data/browser_state/`), so you log into Naukri/Indeed once.
2. Searches each portal for your selected roles, then **ranks every job** — fresher postings,
   fresher-friendly roles, remote/WFH work, higher salary, and tier-1 titles get priority.
3. Has Groq score each top job against your resume (keyword fallback offline).
4. Opens the apply form (capturing portal popups) and pre-fills it from your resume profile,
   reporting which fields it couldn't fill so nothing is silently skipped.
5. In **human** mode you finish + submit (needed for CAPTCHAs / multi-step ATS forms); in **auto** mode it submits for you.
6. Records every application to your history (visible on the Dashboard), skips jobs you've
   already applied to, and — in continuous mode — waits the cooldown, rotates to the next role,
   and runs again until you press Stop.

> **Two ways to use your account (both give you real confirmation emails):**
>
> 1. **`.env` credentials** — set `NAUKRI_EMAIL/NAUKRI_PASSWORD` (and/or
>    `INDEED_EMAIL/INDEED_PASSWORD`). The agent logs in through the portal's own
>    form (no Google sign-in, so Google never blocks it), applies from your
>    account, and confirmation emails land in the email on that account.
> 2. **Dedicated JobHunter browser** (preferred) — the agent opens and reuses its own
>    Chrome window (`data/browser_state/automation_profile/`) with a remote-debugging
>    port. Log in to Naukri/Indeed once in that window; sessions persist, and your real
>    Chrome profile is never touched or closed. If you'd rather manage Chrome yourself,
>    set `BROWSER_CDP_URL=http://localhost:9222` to attach to an already-running instance.
>
> The legacy "copy a slice of your default Chrome profile" path is a **discovery aid
> only** — auto-apply explicitly refuses it (a logged-out copy can never silently
> receive applications); the apply agent requires the dedicated browser or CDP.
>
> Full details, ports, CDP setup, and the login workflow: `docs/browser-setup.md`.
>
> Install the browser engine once: `python -m playwright install chromium`
> Portals block automation aggressively. Start in `human` mode and keep volume low to avoid account bans; a company confirmation email only arrives after a *real* submission.

---

## Configuration

The full reference (every variable, defaults, ranges, validation, recipes,
schema versioning) lives in [`docs/configuration.md`](docs/configuration.md).
Highlights:

| Environment variable | Default | Description |
| --- | --- | --- |
| `OPENAI_API_KEY` / `GROQ_API_KEY` | _(empty)_ | LLM provider; keyword fallback when unset |
| `NAUKRI_EMAIL` / `NAUKRI_PASSWORD` | _(empty)_ | Naukri login for the apply agent (or manual login in the window) |
| `INDEED_EMAIL` / `INDEED_PASSWORD` | _(empty)_ | Indeed login |
| `AUTO_APPLY_MODE` | `human` | `human` (pre-fill, you submit), `auto`, `off` |
| `PIPELINE_APPLY_MODE` | `off` | Pipeline opt-in: `off` = review only, `human`, `auto` |
| `MAX_APPLICATIONS_PER_RUN` | `5` | Cap per run |
| `JOBHUNTER_APP_SECRET` | _(empty)_ | Fernet secret for persisted credentials at rest |

Environment variables are read from `.env`; the dashboard's persisted Settings override them.

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

Liveness probe — returns `{"status": "ok", "version": "<version>"}`.

### `GET /ready`

Readiness probe for orchestrators — verifies the upload directory exists and is
writable. Returns `200 {"status": "ready"}` or `503 {"status": "unavailable",
"problems": [...]}` so a failing disk is visible to the scheduler without a
crash-loop.

---

## Running tests

```bash
uv sync --locked
uv run pytest                 # 550+ tests
# with coverage (CI fails below 60%; actual: 76%):
uv run pytest --cov=jobhunter --cov-report=term-missing --cov-fail-under=60
```

Or with pip: `pip install -r requirements-dev.txt && python -m pytest --cov=jobhunter --cov-report=term-missing`

Test coverage includes the full LangGraph pipeline and safety invariants, the apply agent
(browser flows fully faked), eligibility & relevance gates, discovery sources, persistence
(schema migrations, corruption recovery, round trips), run-state & crash idempotency, the REST
API, the dashboard pages (headless AppTest), form filling, Q&A memory, the CLI and scheduler,
and the minimal Chrome profile copy.

---

## Extending

- **Add a job API:** create a `search_*_jobs` function in `domains/search/api_sources.py` and call it from `domains/search/engine.py`
- **Add a scraper:** follow the existing Playwright patterns in `domains/search/scrapers.py` and register it in `domains/search/engine.py`
- **Use a different LLM:** swap the `ChatOpenAI` in `agent.py` for any LangChain chat model
- **Real ATS submission:** extend the Naukri/Indeed strategies in `automation/strategies.py` (keep the human-in-the-loop and verification gates)

---

## License

MIT