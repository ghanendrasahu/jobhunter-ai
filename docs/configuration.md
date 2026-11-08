# Configuration

JobHunter AI is configured through environment variables and an optional
`.env` file in the project root. Dashboard-saved settings (Settings page)
are layered **on top of** `.env` — they win when both exist. Nothing is
committed to git; `.env` is gitignored and `.env.example` documents every
supported variable.

Quick start:

```powershell
cp .env.example .env   # then edit it
```

All values have safe defaults; **an empty `.env` works** — the pipeline then
runs with keyword matching only and no auto-apply access.

## Environment validation

Startup is deliberately forgiving: invalid *types* fail fast with a pydantic
`ValidationError` (e.g. `SMTP_PORT=99999`, `MAX_FILE_SIZE_MB=0`), while
cross-field misconfigurations are reported without crashing via
`jobhunter.config.validate_config()` (also surfaced by `GET /ready`).
Numeric ranges are enforced at the model layer (`smtp_port`, `max_file_size_mb`,
`browser_debug_port`, `max_experience_years`, `max_applications_per_run`,
`batch_size`, `search_max_concurrency`, `score_max_workers`,
`source_timeout_seconds`, `retry_max_attempts`, `retry_backoff_seconds`,
`manual_login_timeout`, `cooldown_seconds`, `paginate_depth`,
`fetch_full_description_max`).

## Common recipes

### Zero-config local run

```env
# nothing required — keyword matching only, human-in-loop apply
```

### LLM-assisted pipeline (free tier)

```env
GROQ_API_KEY=gsk_...
```

### Email alerts after a run

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASS=your-app-password
NOTIFICATION_EMAIL=you@example.com
```

### Auto-apply to Naukri/Indeed (human-in-loop, recommended)

```env
AUTO_APPLY_MODE=human
NAUKRI_EMAIL=you@naukri.com
NAUKRI_PASSWORD=...
# or leave credentials empty and log in manually in the dedicated browser once
```

### Allow the search pipeline itself to apply (off by default)

```env
PIPELINE_APPLY_MODE=human   # off = review only; auto = submit after verification
```

## All variables

### LLM

| Variable | Default | Notes |
| --- | --- | --- |
| `OPENAI_API_KEY` | _(empty)_ | Optional; keyword fallback works without it |
| `OPENAI_MODEL` | `gpt-4o-mini` | |
| `GROQ_API_KEY` | _(empty)_ | Preferred when set (OpenAI-compatible) |
| `GROQ_MODEL` | `openai/gpt-oss-20b` | |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | |

### Optional job APIs

| Variable | Default | Notes |
| --- | --- | --- |
| `ADZUNA_APP_ID` | _(empty)_ | Both or neither — half-configured reports a warning |
| `ADZUNA_API_KEY` | _(empty)_ | |
| `JOOBLE_API_KEY` | _(empty)_ | |
| `JSEARCH_API_KEY` | _(empty)_ | RapidAPI |

### Email notifications

| Variable | Default | Notes |
| --- | --- | --- |
| `SMTP_HOST` | _(empty)_ | |
| `SMTP_PORT` | `587` | 1–65535 |
| `SMTP_USER` / `SMTP_PASS` | _(empty)_ | Use an app password |
| `NOTIFICATION_EMAIL` | _(empty)_ | |

### API security

| Variable | Default | Notes |
| --- | --- | --- |
| `JOBHUNTER_API_KEY` | _(empty)_ | Empty = open (local only) |
| `API_RATE_LIMIT` | `20/minute` | |
| `JOBHUNTER_TRUST_PROXY_HEADERS` | `true` | Behind Render/proxy |
| `CORS_ORIGINS` | _(empty)_ | Comma-separated exact origins |
| `MAX_FILE_SIZE_MB` | `10` | ≥ 1 |
| `JOBHUNTER_APP_SECRET` | _(empty)_ | Fernet master secret for persisted portal credentials at rest |
| `LOG_JSON` | `false` | Single-line JSON logs |

### Auto-apply agent

| Variable | Default | Notes |
| --- | --- | --- |
| `NAUKRI_EMAIL` / `NAUKRI_PASSWORD` | _(empty)_ | Or log in manually in the dedicated browser |
| `INDEED_EMAIL` / `INDEED_PASSWORD` | _(empty)_ | |
| `AUTO_APPLY_MODE` | `human` | `human` (pre-fill, you submit) / `auto` / `off` |
| `PIPELINE_APPLY_MODE` | `off` | LangGraph pipeline approval: `off` / `human` / `auto` |
| `MAX_APPLICATIONS_PER_RUN` | `5` | ≥ 1 |
| `HEADLESS_BROWSER` | `false` | |
| `BROWSER_CHANNEL` | `chrome` | `chrome` (installed) or `chromium` (bundled) |
| `BROWSER_USE_DEDICATED_PROFILE` | `true` | Dedicated persistent JobHunter window (preferred) |
| `BROWSER_PROFILE_DIR` | `data/browser_state/automation_profile` | |
| `BROWSER_DEBUG_PORT` | `9222` | 1–65535 |
| `BROWSER_CDP_URL` | _(empty)_ | Attach to an already-running Chrome instead of launching |
| `BROWSER_USER_DATA_DIR` | _(empty)_ | Auto-detected when empty |
| `BROWSER_STATE_DIR` | `data/browser_state` | |
| `MANUAL_LOGIN_TIMEOUT` | `180` | Seconds; ≥ 0 |
| `FRESHER_ONLY` | `true` | Skip jobs requiring more than `MAX_EXPERIENCE_YEARS` |
| `MAX_EXPERIENCE_YEARS` | `2` | 0–10 |
| `BATCH_SIZE` | `10` | Applications per continuous-mode cycle |
| `COOLDOWN_SECONDS` | `300` | Pause between cycles |
| `PRIORITIZE_REMOTE` | `true` | Rank remote/WFH first |
| `QUERY_VARIANTS` | `fresher,entry level,remote` | Comma-separated, rotated per cycle |
| `SEARCH_LOCATIONS` | `India,Bengaluru,Remote,Hybrid` | |
| `PAGINATE_DEPTH` | `3` | |

### Search & runtime tuning

| Variable | Default | Notes |
| --- | --- | --- |
| `FETCH_FULL_DESCRIPTIONS` | `false` | Fetch full job description pages |
| `FETCH_FULL_DESCRIPTION_MAX` | `5` | ≥ 1 |
| `SEARCH_MAX_CONCURRENCY` | `2` | Planned queries searched concurrently |
| `SCORE_MAX_WORKERS` | `4` | Threads for LLM relevance scoring |
| `SOURCE_TIMEOUT_SECONDS` | `45` | Hard per-source timeout; failures never stop other sources |
| `RETRY_MAX_ATTEMPTS` | `3` | Bounded retries for navigation/browser ops |
| `RETRY_BACKOFF_SECONDS` | `2.0` | Backoff between retries |

### Paths

| Variable | Default | Notes |
| --- | --- | --- |
| `UPLOAD_DIR` | `uploads` | |
| `HISTORY_DIR` | `history` | SQLite DB lives here |
| `RESUMES_DIR` | `resumes` | Saved resume copies |
| `JOBHUNTER_ROOT` | repo root | Project root override for installed deployments |

## Persistence & schema

All runtime state lives in a single SQLite database, `history/history.db`
(`resumes`, `histories`, `settings`, `profile_store`, `qa_answers`, `runs`,
`run_events`, `run_source_metrics`, `submission_attempts`). It is created
automatically on first use. The schema is versioned with `PRAGMA user_version`
(current: **2**) and upgraded idempotently at startup by
`jobhunter.storage.schema`; if the file is corrupt it is moved aside to
`history.db.corrupt-<timestamp>` and a fresh database is created rather than
crashing. Portal credentials in `settings` are Fernet-encrypted when
`JOBHUNTER_APP_SECRET` is set.

Legacy `*.json` history/profile files from pre-SQLite versions are imported
once, automatically.
