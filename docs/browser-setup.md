# Browser setup & the login workflow

JobHunter automates real portals (Naukri, Indeed) with a real browser session.
This page explains how the browser works, how to log in, and how to troubleshoot.

## The dedicated JobHunter browser window

Auto-apply never uses your normal Chrome profile. It uses its own Chrome window
and profile:

- Path: `data/browser_state/automation_profile/` (configurable via `BROWSER_PROFILE_DIR`)
- Launched once with a remote debugging port (`BROWSER_DEBUG_PORT`, default `9222`)
- Reused across every run — log in once per portal and you stay logged in
- Never closes or modifies your regular Chrome; you can keep using your normal browser

The first time you run the apply agent (or click **Apply → Connect browser** in
the dashboard), the dedicated window opens. Sign into Naukri and Indeed there
like a normal user. Sessions persist on disk, so this is a one-time step per portal.

Check status from the dashboard: **Auto Apply → JobHunter Browser** shows
`Browser connected` / `Browser not connected`, with per-portal login checks.

## Supported application portals

Only these have an automated application strategy and may receive applications
from the pipeline or the apply agent:

| Portal | Auto-apply | Notes |
| ------ | ---------- | ----- |
| Naukri | Yes        | `automation/strategies.py` (`naukri`) |
| Indeed | Yes        | `automation/strategies.py` (`indeed`) |

Everything else is **discovery-only** — jobs are shown, scored and can be
opened in your browser, but never submitted automatically.

## Discovery-only sources

These sources feed results to you but are never auto-applied and never fall
through to another portal:

- LinkedIn (`linkedin`)
- Google Jobs (`google_jobs`) — a search aggregator, never an application portal
- Cutshort (`cutshort`), Foundit (`foundit`), Hirist (`hirist`), Internshala (`internshala`)
- Portal search links (one-click "search X on <portal>" results)

Discovery-only jobs appear in results, carry `discovery_only=True`, and route
to `needs_review` in the apply layer — never to a submission.

## CDP attach (alternative to launching a dedicated window)

If you prefer managing the browser yourself, launch Chrome once with a debugging
port and point JobHunter at it:

```bash
chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\path\to\dedicated_profile"
# then:
BROWSER_CDP_URL=http://localhost:9222
```

With `BROWSER_CDP_URL` set, the agent attaches to that Chrome instead of
launching its own. Your normal profile stays untouched; only the tabs JobHunter
opens are managed/closed by it.

## The login workflow

1. **`.env` credentials (optional).** Set `NAUKRI_EMAIL` / `NAUKRI_PASSWORD`
   (and/or `INDEED_EMAIL` / `INDEED_PASSWORD`). The agent signs in through the
   portal's own login form (avoids Google's automated-sign-in blocks) and
   applies from your account — confirmation emails land in that account's inbox.
2. **Manual login (default, recommended).** Leave the credentials empty. The
   dedicated window opens; you log in like a human; sessions persist.
3. **Timeouts.** You have `MANUAL_LOGIN_TIMEOUT` seconds (default 180) per
   portal to complete a manual login; the run skips the portal if you miss it,
   it never blocks forever.
4. **2FA / CAPTCHAs.** Stay in `auto_apply_mode=human` — the agent pre-fills the
   form and you finish (and submit) it yourself, in the same window.

## If anything goes wrong

| Symptom | Fix |
| --- | --- |
| "Dedicated browser could not be started" | Chrome not installed or port in use — close whatever holds port 9222, or install Chrome; the bundled Chromium is used only if `BROWSER_CHANNEL=chromium` |
| "Not logged in" at every run | Log in once in the dedicated window; persisted sessions only survive while the profile dir is intact — don't delete `data/browser_state/` |
| Portals block automation | Start in `human` mode, keep volume low (`MAX_APPLICATIONS_PER_RUN` ≤ 5), respect cooldowns (`COOLDOWN_SECONDS`) |
| "Chrome 136+ blocks automated control" | Expected — that's why JobHunter uses its own window instead of your normal profile |
| Chromium not found for scraping | `uv run playwright install chromium` (scraping only — the apply agent uses real Chrome) |
