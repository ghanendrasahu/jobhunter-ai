# Safety behavior & limitations

JobHunter applies to real jobs from your real accounts. This document states
exactly what it will and will never do, and the known limits.

## What the agent will never do

These guarantees are enforced in code, not just in documentation (see
`tests/test_invariants.py`, which asserts each one):

- **Never apply to a job PH5 eligibility rejected.** Eligibility is a hard
  deterministic gate that runs before any scoring. If it says `skip`, the job
  is never scored, never ranked as actionable, never applied.
- **Never let an LLM override eligibility.** LLMs may advise on relevance;
  they cannot promote an ineligible job or demote a deterministic `skip`.
- **Never treat UNKNOWN experience as zero.** Missing knowledge routes to
  `needs_review` for you, never to an application.
- **Never fabricate information.** Missing required fields, unknown answers,
  and blank profile data are reported as `needs_review` — the agent never
  invents employers, dates, salaries, skills, or answers.
- **Never auto-fill sensitive controls.** Passwords, OTPs, CAPTCHAs and other
  security/legal/demographic fields are never touched, even from Q&A memory.
- **Never auto-apply to discovery-only sources.** LinkedIn, Google Jobs,
  Cutshort, Foundit, Hirist and Internshala are information sources — jobs
  shown there are never submitted.
- **Never apply to an unsupported portal.** Only Naukri and Indeed have
  automated strategies; anything else surfaces for your review.
- **Never fall back to a logged-out copied profile.** Auto-apply requires the
  dedicated authenticated browser; if it cannot be established, the run is
  refused entirely — it never applies from your default/logged-out profile.
- **Never record a submission as applied without verifying it.** Only after a
  deterministic post-click check (success marker in URL or page text) is a job
  marked `submitted`. Unconfirmed attempts surface as `needs_review`.
- **Never re-apply after a crash.** A crash between clicking submit and
  recording the outcome leaves a durable marker; the job is never auto-retried.
- **Never submit twice.** Applied-job history plus submission-attempt markers
  prevent duplicates, including across restarts.

## Pipeline safety model

```
sources → search plan → normalization → dedupe
→ PH5 eligibility HARD GATE (deterministic)
→ PH6 relevance ranking (deterministic first, LLM-flavored refinement)
→ supported-portal contract → dedicated browser → form fill
→ human-required questions surface for you
→ submit → post-click verification → honest outcome
```

Every outcome per job is explainable end to end: eligibility decision +
reasons → relevance score + components → application route decision →
recorded outcome. See the dashboard's job cards ("Why this score") and
**Needs Review** queue for the full audit trail.

## Honest outcome semantics

| Status | Meaning |
| --- | --- |
| `submitted` | Post-click verification positively confirmed the application |
| `handed_off` | Form pre-filled (human mode); you complete and submit it |
| `needs_review` | Stopped before submit, or submit unverified — verify in the portal |
| `already_applied` | Already in your history — skipped |
| `discovery_only` / `recorded` / `opened` | Browsable/record-only; never submitted |
| `failed` | Deterministic failure (browser, crash) — nothing was (or could be) applied |
| `skipped` / `deferred` | Not eligible, or run cap/stop reached before attempting |

## Known limitations

- **Portals change markup.** Naukri/Indeed update their pages; selectors can
  rot. Failures surface as `failed` outcomes with clear reasons — nothing is
  applied blindly.
- **CAPTCHAs and bot checks** cannot be solved automatically. Use `human`
  mode; you stay in the loop for these.
- **Account risk.** Automation can trigger portal anti-bot systems; keep
  volume low (`MAX_APPLICATIONS_PER_RUN` default 5) and respect `COOLDOWN_SECONDS`.
- **No guarantee of acceptance** — JobHunter submits applications; it cannot
  influence hiring outcomes.
- **Discovery-only apply flow is manual.** Google Jobs/LinkedIn listings must
  be applied to by you in your browser.
- **LLM availability.** Without an API key, query generation and scoring fall
  back to deterministic keyword matching; safety behavior is unchanged.
- **Chrome required** for the apply agent (the dedicated window). Bundled
  Chromium is only for scraping and is skipped automatically if unavailable.
- **Submission verification is heuristic by nature** — it inspects the visible
  page text and URL for deterministic success markers; when in doubt it reports
  `needs_review` rather than claiming success.

## Deleting data

`history/history.db` is a single SQLite database (resumes, applications, Q&A
memory, runs, attempt markers). Deleting it wipes application history but keeps
your code and browser logins. The Settings page can clear history or export it
as CSV.
