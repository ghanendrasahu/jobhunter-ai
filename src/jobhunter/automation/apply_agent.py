"""Continuous, single-window application agent for Naukri / Indeed.

Modes:
- **human** (default): pre-fill forms and let the user submit (needed for
  CAPTCHAs / multi-step ATS).
- **auto**: additionally click submit for forms with nothing missing; forms
  missing profile data are handed off to the user.
- **off**: does nothing.

Continuous mode runs in batches of ``batch_size`` applications per cycle, pauses
``cooldown_seconds`` between cycles, and keeps going until a ``stop_event`` is
set (or the user stops via the dashboard). Every portal is processed in one
reused tab; each job opens in a new tab which is closed after applying, so the
browser window stays tidy and existing logins are never re-prompted.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from jobhunter.agent import _default_llm
from jobhunter.automation import strategies
from jobhunter.automation.browser import BrowserSession, build_session, is_logged_in
from jobhunter.automation.candidate import build_candidate
from jobhunter.automation.evaluator import evaluate_job
from jobhunter.automation.form_filler import fill_form
from jobhunter.automation.prioritizer import sort_jobs_by_priority
from jobhunter.automation.profile import profile_from_resume
from jobhunter.automation.roles import priority_role_titles
from jobhunter.automation.strategies import fill_input
from jobhunter.config import Settings, get_settings
from jobhunter.domains.eligibility import evaluate_eligibility
from jobhunter.domains.search.plan import _FRESHER_TERMS, dedupe_fresher_terms
from jobhunter.storage.history import load_applied_jobs, record_application_outcome, save_applied_jobs

logger = logging.getLogger(__name__)

StatusCallback = Callable[[str, str, str], None]  # (level, stage, message)


class ApplyAgent:
    """Coordinates portal login, job discovery, evaluation, and applying."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._log: list[dict[str, str]] = []
        self._on_status: StatusCallback | None = None
        self._llm: Any = None
        self._stop_event = threading.Event()
        self._cycle_budget: int = 5
        self._cooldown: int = 300
        self._prioritize_remote: bool = True

    # ------------------------------------------------------------------ public
    def run(
        self,
        query: str,
        resume_text: str,
        portals: list[str] | None = None,
        mode: str | None = None,
        max_applications: int | None = None,
        resume_pdf: str | None = None,
        on_status: StatusCallback | None = None,
        profile: dict | None = None,
        roles: list[str] | None = None,
        continuous: bool = False,
        stop_event: threading.Event | None = None,
        batch_size: int | None = None,
        cooldown_seconds: int | None = None,
        cycle_callback: Callable[[int, list[dict]], None] | None = None,
        prioritize_remote: bool | None = None,
    ) -> dict[str, Any]:
        """Run the apply agent and return results + a log.

        ``mode`` defaults to ``auto_apply_mode`` from settings (``human``).
        ``roles`` (job titles) drive what is searched; when given, each cycle
        rotates to the next role. ``stop_event`` lets the dashboard stop a
        continuous run cleanly.
        """
        mode = mode or self.settings.auto_apply_mode
        if mode == "off":
            self._report("info", "config", "Auto-apply is disabled (auto_apply_mode=off)")
            return {"results": [], "log": self._log, "mode": mode}

        max_applications = max_applications or self.settings.max_applications_per_run
        portals = [p for p in (portals or ["naukri", "indeed"]) if p in strategies.PORTALS]
        profile = profile or profile_from_resume(resume_text)
        self._on_status = on_status
        self._llm = _default_llm()
        if stop_event is not None:
            self._stop_event = stop_event
        self._cycle_budget = batch_size or max_applications
        self._cooldown = cooldown_seconds or self.settings.cooldown_seconds
        if prioritize_remote is not None:
            self._prioritize_remote = prioritize_remote
        else:
            self._prioritize_remote = self.settings.prioritize_remote

        if roles:
            query = roles[0]
            self._report("info", "start", f"Priority roles: {', '.join(roles)}")
        if self.settings.fresher_only:
            self._report(
                "info", "start",
                f"Fresher mode on — queries include 'fresher' and jobs requiring "
                f"more than {self.settings.max_experience_years} years are skipped.",
            )

        self._report("info", "start", f"Mode={mode} | Portals={portals} | Batch={self._cycle_budget}")
        self._report("info", "profile", f"Profile: {profile['email'] or 'no email'} | skills: {len(profile['skills'])}")

        priority_titles = priority_role_titles(
            [{"title": r} for r in roles] if roles else None
        )

        results: list[dict] = []
        applied = load_applied_jobs(resume_text)
        session = build_session(self.settings)
        try:
            session.start()
            if session.using_cdp and session.using_dedicated_profile:
                if session.reused_existing:
                    self._report(
                        "info", "browser",
                        "Browser connected — reusing your dedicated JobHunter window and logins.",
                    )
                else:
                    self._report(
                        "info", "browser",
                        "Browser started — your dedicated JobHunter window is open. Log in to "
                        "Naukri/Indeed once; sessions persist between runs.",
                    )
            elif session.using_cdp:
                self._report(
                    "info", "browser",
                    "Browser connected — attached to the configured CDP endpoint.",
                )
            else:
                self._report(
                    "info", "browser",
                    "Using your default Chrome profile (existing logins reused). "
                    if session.using_default_profile
                    else "Using dedicated browser profile.",
                )

            cycle = 0
            while True:
                cycle += 1
                cycle_query = _query_for_cycle(query, roles, cycle, self.settings)
                self._report("info", "run", f"--- Cycle {cycle}: '{cycle_query}' ---")
                for portal in portals:
                    if self._stop_event.is_set():
                        break
                    try:
                        outcomes = self._process_portal(
                            session, portal, cycle_query, resume_text, profile,
                            mode, max_applications, applied, priority_titles,
                            resume_pdf,
                        )
                        results.extend(outcomes)
                    except Exception as exc:
                        logger.exception("Portal %s failed", portal)
                        self._report("error", portal, f"Failed: {exc}")
                if cycle_callback is not None:
                    try:
                        cycle_callback(cycle, results)
                    except Exception:
                        pass

                if not continuous:
                    break
                if self._stop_event.is_set():
                    break
                self._report(
                    "info", "run",
                    f"Cycle done — pausing {self._cooldown}s (Stop anytime).",
                )
                if self._sleep_interruptible(self._cooldown):
                    break
        finally:
            try:
                session.close_all_pages()
            except Exception:
                pass
            session.stop()
            self._report("info", "browser", "Browser disconnected — the dedicated window stays open for the next run.")

        return {"results": results, "log": self._log, "mode": mode, "cycles": cycle}

    def _sleep_interruptible(self, seconds: int) -> bool:
        """Sleep in small chunks, returning True if a stop was requested."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self._stop_event.is_set():
                self._report("info", "run", "Stop requested — finishing run.")
                return True
            try:
                time.sleep(1)
            except KeyboardInterrupt:
                return True
        return False

    # ------------------------------------------------------------------ portals
    def _process_portal(
        self,
        session: BrowserSession,
        portal: str,
        query: str,
        resume_text: str,
        profile: dict,
        mode: str,
        max_applications: int,
        applied: set[str],
        priority_titles: set[str],
        resume_pdf: str | None = None,
    ) -> list[dict]:
        outcomes: list[dict] = []
        page = session.new_tab()

        if not self._ensure_login(page, portal):
            self._report("error", portal, "Login failed or credentials missing — skipping portal")
            session.close_page(page)
            return outcomes

        self._report("info", portal, f"Searching '{query}'")
        try:
            self._goto(page, strategies.build_search_url(portal, query))
        except Exception as exc:
            self._report("error", portal, f"Could not open search page: {exc}")
            session.close_page(page)
            return outcomes
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3500)

        obstacle = strategies.detect_obstacle(page.url, page.inner_text("body")[:4000])
        if obstacle:
            self._report(
                "warning", portal,
                f"Search blocked by a bot check ({obstacle}). You can complete it in "
                f"the browser window (the agent will continue after a refresh), or skip this portal.",
            )
            session.close_page(page)
            return outcomes

        jobs = strategies.collect_cards(page, portal, max_results=max(10, max_applications * 2))
        jobs = sort_jobs_by_priority(jobs, priority_titles, self._prioritize_remote)
        self._report("info", portal, f"{len(jobs)} jobs found")

        candidate = build_candidate(resume_text, profile=profile) if resume_text else None
        attempts = 0
        for job in jobs:
            if attempts >= max_applications:
                break
            if self._stop_event.is_set():
                break

            job_id = job.get("id") or ""
            if job_id in applied or job.get("url") in applied:
                self._report("info", portal, f"Skipping already-applied {job.get('title', '?')} @ {job.get('company', '?')}")
                continue

            if self.settings.fresher_only:
                required = strategies.job_experience_years(job)
                if required is not None and required > self.settings.max_experience_years:
                    self._report(
                        "info", portal,
                        f"Skipping {job.get('title', '?')} @ {job.get('company', '?')} — requires {required}+ yrs",
                    )
                    continue

            eligibility = evaluate_eligibility(job, candidate=candidate, llm=self._llm)
            if eligibility.decision == "skip":
                self._report(
                    "warning", portal,
                    f"HARD SKIP {job.get('title', '?')} @ {job.get('company', '?')} — {'; '.join(eligibility.reasons) or 'not eligible'}",
                )
                continue
            if eligibility.decision == "review":
                detail = "; ".join(eligibility.reasons) or "; ".join(eligibility.exposed) or "needs review"
                self._report(
                    "warning", portal,
                    f"REVIEW {job.get('title', '?')} @ {job.get('company', '?')} — {detail}",
                )
                self._record_outcome(resume_text, job, {
                    "status": "needs_review",
                    "detail": detail,
                })
                continue

            evaluation = evaluate_job(job, resume_text, self._llm)
            self._report(
                "info", portal,
                f"{job.get('title', '?')} @ {job.get('company', '?')} — {evaluation['decision']} ({evaluation['score']}%)",
            )
            if evaluation["decision"] != "apply":
                continue

            attempts += 1  # counts every apply attempt, keeping the run bounded
            outcome = self._apply_job_with_recovery(session, portal, job, profile, mode, resume_pdf)
            outcome["evaluation"] = evaluation
            outcomes.append(outcome)

            if outcome.get("status") == "submitted":
                # Only a truly submitted application marks the job as applied;
                # everything else stays eligible for a later run.
                self._record_application(resume_text, job, outcome)
                applied.add(job_id)
                if job.get("url"):
                    applied.add(job["url"])
            else:
                # Persist the outcome (handed_off/failed/blocked/needs_review/
                # no_apply_button) WITHOUT marking the job as applied, so it
                # remains eligible to be (re)submitted on a later run.
                self._record_outcome(resume_text, job, outcome)
                if mode == "human" and outcome.get("status") == "handed_off":
                    # Human-in-the-loop: pause so the user can finish the form.
                    self._report("info", portal, "Waiting 20s for you to complete the form in the browser window…")
                    time.sleep(20)

        session.close_page(page)
        return outcomes

    @staticmethod
    def _goto(page, url: str, timeout: int = 45000, retries: int = 3) -> None:
        """Navigate with retries to survive navigation races (Naukri redirects/lightboxes)."""
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                page.goto(url, timeout=timeout, wait_until="domcontentloaded")
                return
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Navigation to %s failed on attempt %d/%d: %s",
                    url, attempt + 1, retries, exc,
                )
                try:
                    page.wait_for_timeout(2500)
                except Exception:
                    return
        raise last_error  # type: ignore[misc]  # mypy can't prove non-None here

    def _apply_to_job(
        self,
        session: BrowserSession,
        portal: str,
        job: dict,
        profile: dict,
        mode: str,
        resume_pdf: str | None,
    ) -> dict:
        base = {
            "job_id": job.get("id", "unknown"),
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "source": portal,
        }

        job_page = session.new_tab()
        try:
            self._goto(job_page, job.get("url", ""))
        except Exception as exc:
            session.close_page(job_page)
            return {**base, "status": "failed", "detail": f"Could not open job page: {exc}"}
        job_page.wait_for_timeout(2500)

        obstacle = strategies.detect_obstacle(job_page.url, job_page.inner_text("body")[:4000])
        if obstacle:
            session.close_page(job_page)
            return {**base, "status": "blocked", "detail": f"Obstacle: {obstacle}"}

        clicked, form_page = self._click_apply_capture_popup(session, job_page)
        if not clicked:
            session.close_page(job_page)
            return {**base, "status": "no_apply_button", "detail": "No apply button found (maybe already applied or external ATS)."}

        try:
            form_page.wait_for_timeout(3000)
            form_page.wait_for_function(
                """() => {
                    const inputs = document.querySelectorAll('input, textarea, select');
                    for (const el of inputs) {
                        if (el.offsetParent !== null) return true;
                    }
                    return false;
                }""",
                timeout=15000,
            )
        except Exception:
            pass  # some forms are JS-spa modals without a stable body first

        stats = fill_form(form_page, profile, resume_pdf)
        missing = stats.get("missing", [])

        if mode == "human":
            detail = f"Form pre-filled ({stats['filled']} fields). Complete & submit in the browser window."
            if missing:
                detail += f" Missing: {', '.join(missing)}."
            result = {
                **base, "status": "handed_off",
                "detail": detail,
                "filled_fields": stats,
            }
        elif missing:
            result = {
                **base, "status": "needs_review",
                "detail": f"Form filled but missing: {', '.join(missing)} — complete in the browser window.",
                "filled_fields": stats,
            }
        else:
            submitted = self._submit_and_advance(form_page, profile, resume_pdf)
            if submitted:
                result = {**base, "status": "submitted", "detail": "Application submitted automatically.", "filled_fields": stats}
            else:
                result = {**base, "status": "needs_review", "detail": "Form filled; submit button not found — complete manually.", "filled_fields": stats}

        try:
            session.close_page(form_page)
        except Exception:
            pass
        session.close_page(job_page)
        return result

    def _apply_job_with_recovery(
        self,
        session: BrowserSession,
        portal: str,
        job: dict,
        profile: dict,
        mode: str,
        resume_pdf: str | None,
        retries: int = 2,
    ) -> dict:
        """Apply to one job, recovering from a browser crash with bounded retries.

        When Playwright reports the browser/context is closed (e.g. the Chrome
        window was closed mid-application), the session is re-launched/reattached
        and the job is retried up to ``retries`` times instead of aborting the
        whole run. The rest of the batch keeps going.
        """
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                return self._apply_to_job(session, portal, job, profile, mode, resume_pdf)
            except Exception as exc:
                if not _browser_crashed(exc):
                    raise
                last_error = exc
                logger.warning(
                    "Browser crash while applying to %s (attempt %d/%d): %s",
                    job.get("id", "?"), attempt + 1, retries, exc,
                )
                try:
                    session.restart()
                except Exception as restart_exc:
                    logger.error("Browser restart failed: %s", restart_exc)
                    break
        return {
            "job_id": job.get("id", "unknown"),
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "source": portal,
            "status": "failed",
            "detail": f"Browser crashed during application: {last_error or 'unknown error'}",
        }

    def _record_outcome(self, resume_text: str, job: dict, outcome: dict) -> None:
        """Persist a non-submitted outcome without marking the job as applied."""
        try:
            record_application_outcome(resume_text, job, outcome)
        except Exception as exc:
            logger.warning("Failed to record outcome: %s", exc)

    def _click_apply_capture_popup(self, session: BrowserSession, page) -> tuple[bool, Any]:
        """Click Apply, returning ``(clicked, form_page)``.

        Portals (Naukri/Indeed/LinkedIn) often open the application in a new tab
        (``target=_blank``). We capture that popup so the form is filled on the
        real form page rather than the stale job listing.
        """
        context = getattr(session, "_context", None)
        if context is None:
            clicked = strategies.click_apply(page)
            return clicked, page
        try:
            with context.expect_page(timeout=8000) as popup_info:
                clicked = strategies.click_apply(page)
            if clicked:
                popup = popup_info.value
                try:
                    popup.wait_for_load_state("domcontentloaded")
                except Exception:
                    pass
                return True, popup
            return clicked, page
        except Exception:
            # No popup opened (form is a modal in the same page) — or click failed.
            clicked = strategies.click_apply(page)
            return clicked, page

    def _submit_and_advance(self, form_page, profile: dict, resume_pdf: str | None) -> bool:
        """Fill, advance multi-step forms, and click submit.

        Naukri instant-apply is multi-step: fields are revealed per step and the
        Submit button only exists on the final step. We cycle fill → click
        Continue/Next → refill newly revealed fields → submit, up to 5 steps.
        Returns True only when a final submit action was clicked.
        """
        seen_signatures: set[frozenset[str]] = set()
        for _ in range(5):
            try:
                fill_form(form_page, profile, resume_pdf)
            except Exception:
                return False
            if strategies.click_submit(form_page):
                return True
            if not strategies.click_step_advance(form_page):
                return False
            try:
                form_page.wait_for_timeout(1500)
            except Exception:
                return False
            signature = _visible_controls(form_page)
            if signature in seen_signatures:
                return False
            seen_signatures.add(signature)
        return False

    # ------------------------------------------------------------------ support
    def _ensure_login(self, page, portal: str) -> bool:
        selectors = strategies.login_selector(portal)
        login_url = strategies.PORTALS[portal]["login_url"]
        login_markers = ("login", "auth", "signin")

        # Always open the portal login URL first: when already logged in it
        # redirects straight to the homepage, which is the login check.
        try:
            page.goto(login_url, timeout=45000)
            page.wait_for_load_state("domcontentloaded")
        except Exception as exc:
            self._report("error", portal, f"Could not open portal page: {exc}")
            return False

        redirected_away = not any(marker in (page.url or "").lower() for marker in login_markers)
        already_logged_in = redirected_away or _safe_logged_in(page, selectors["logged_in"])
        if not already_logged_in:
            # Some portals (Naukri) show the login page even when logged in; the
            # logged-in indicator only appears on the homepage.
            home_url = strategies.PORTALS[portal].get("home_url", "")
            if home_url:
                try:
                    page.goto(home_url, timeout=45000)
                    page.wait_for_load_state("domcontentloaded")
                    already_logged_in = _safe_logged_in(page, selectors["logged_in"])
                except Exception as exc:
                    logger.warning("Homepage login check failed for %s: %s", portal, exc)
        if already_logged_in:
            self._report("info", portal, "Already logged in")
            return True

        email = getattr(self.settings, f"{portal}_email", "")
        password = getattr(self.settings, f"{portal}_password", "")

        # No credentials configured -> let the user log in manually in the
        # opened browser window (sessions persist between runs, so it's one-time).
        if not email or not password:
            self._report("info", portal, f"No {portal} credentials in .env — logging in manually for you")
            return self._wait_manual_login(page, portal)

        self._report("info", portal, "Logging in with .env credentials…")
        try:
            if selectors["email"] and not fill_input(page, selectors["email"], email):
                strategies.click_by_text(page, "Continue")
                page.wait_for_timeout(2000)
                fill_input(page, selectors["email"], email)
            if selectors["password"]:
                fill_input(page, selectors["password"], password)
            if selectors["button"]:
                _click_selector(page, selectors["button"])
            else:
                strategies.click_by_text(page, "Sign in")
            page.wait_for_timeout(4000)
        except Exception as exc:
            self._report("error", portal, f"Login failed: {exc}")
            return False

        obstacle = strategies.detect_obstacle(page.url, page.inner_text("body")[:4000])
        if obstacle:
            self._report(
                "warning", portal,
                f"Login blocked by verification ({obstacle}). Complete it in the browser window, "
                f"or log in on your normal Chrome and re-run.",
            )
            return True  # user can finish; session persists for next run

        # Verify the login actually succeeded before proceeding.
        home_url = strategies.PORTALS[portal].get("home_url", "")
        logged_in = False
        if home_url:
            try:
                page.goto(home_url, timeout=45000)
                page.wait_for_load_state("domcontentloaded")
                logged_in = _safe_logged_in(page, selectors["logged_in"])
            except Exception as exc:
                logger.warning("Login verification failed for %s: %s", portal, exc)
        if logged_in:
            self._report("info", portal, "Login successful")
            return True

        self._report("warning", portal, "Auto-login did not complete — finishing login manually")
        return self._wait_manual_login(page, portal)

    def _wait_manual_login(self, page, portal: str) -> bool:
        """Poll until the user completes login in the browser window."""
        selectors = strategies.login_selector(portal)
        deadline = time.time() + self.settings.manual_login_timeout
        self._report(
            "info", portal,
            f"Log in now in the browser window (waiting up to {self.settings.manual_login_timeout}s)…",
        )
        while time.time() < deadline:
            current_url = ""
            try:
                current_url = (page.url or "").lower()
            except Exception:
                pass
            # Logged in when the indicator appears, or when the page has
            # navigated away from the login/auth URL (Naukri/Indeed redirect
            # to their homepages after a successful login).
            redirected = bool(current_url) and not any(
                marker in current_url for marker in ("login", "auth", "signin")
            )
            logged_in = False
            try:
                logged_in = is_logged_in(page, selectors["logged_in"])
            except Exception:
                pass
            if logged_in or redirected:
                self._report("info", portal, "Login detected — continuing")
                return True
            try:
                page.wait_for_timeout(5000)
            except Exception:
                self._report("warning", portal, "Browser window was closed during login wait — skipping portal")
                return False
        self._report("warning", portal, "Manual login not detected in time — skipping portal")
        return False

    def _record_application(self, resume_text: str, job: dict, outcome: dict) -> None:
        try:
            job_id = outcome.get("job_id", job.get("id", "unknown"))
            save_applied_jobs(resume_text, [job_id], [{
                "job_id": job_id,
                "title": job.get("title"),
                "company": job.get("company"),
                "source": job.get("source", job.get("portal")),
                "url": job.get("url", ""),
                "match_score": outcome.get("evaluation", {}).get("score"),
                "status": outcome.get("status", "submitted"),
                "detail": outcome.get("detail", ""),
                "applied_at": _now_iso(),
            }])
        except Exception as exc:
            logger.warning("Failed to record application: %s", exc)

    def _report(self, level: str, stage: str, message: str) -> None:
        entry = {"level": level, "stage": stage, "message": message}
        self._log.append(entry)
        logger.info("[%s] %s: %s", level, stage, message)
        if self._on_status is not None:
            try:
                self._on_status(level, stage, message)
            except Exception:
                pass


def _query_for_cycle(base_query: str, roles: list[str] | None, cycle: int, settings: Settings) -> str:
    """Pick the query for a continuous cycle.

    Rotates through the user's chosen roles first, then applies fresher/remote
    variant suffixes across cycles so the search keeps widening coverage. In
    fresher-only mode the word ``fresher`` (or an equivalent term) appears at
    most once per query, no matter which variants are active.
    """
    variants = [v.strip() for v in (settings.query_variants or "").split(",") if v.strip()]

    if roles:
        role = roles[(cycle - 1) % len(roles)]
        suffix = variants[(cycle - 1) // len(roles) % len(variants)] if variants else ""
        query = f"{role} {suffix}".strip()
    elif variants:
        query = f"{base_query} {variants[(cycle - 1) % len(variants)]}".strip()
    else:
        query = base_query

    if settings.fresher_only:
        query = dedupe_fresher_terms(query)
        if not any(term in query.lower() for term in _FRESHER_TERMS):
            query = f"{query} fresher".strip()
    return query


def _browser_crashed(exc: Exception) -> bool:
    """Return True when a Playwright error means the browser/context is gone."""
    try:
        from playwright._impl._errors import TargetClosedError

        if isinstance(exc, TargetClosedError):
            return True
    except Exception:
        pass
    text = str(exc).lower()
    return any(
        marker in text
        for marker in ("has been closed", "target closed", "context closed", "browser closed")
    )


def _click_selector(page, selector: str) -> bool:
    if not selector:
        return False
    try:
        page.click(selector, timeout=5000)
        return True
    except Exception:
        return False


def _safe_logged_in(page, logged_in_selector: str) -> bool:
    """is_logged_in that never raises (browser may have closed)."""
    try:
        return is_logged_in(page, logged_in_selector)
    except Exception:
        return False


def _visible_controls(page) -> frozenset[str]:
    """Signature of currently visible form controls (across frames)."""
    keys: set[str] = set()
    for frame in page.frames:
        try:
            controls = frame.query_selector_all("input, textarea, select")
        except Exception:
            continue
        for handle in controls:
            try:
                if not handle.is_visible():
                    continue
                keys.add(handle.evaluate(
                    "el => (el.name || '') + '|' + (el.id || '') + '|' + (el.type || '')"
                ))
            except Exception:
                continue
    return frozenset(keys)


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat()


def run_application_pipeline(
    query: str,
    resume_text: str,
    resume_pdf: str | None = None,
    portals: list[str] | None = None,
    mode: str | None = None,
    max_applications: int | None = None,
    on_status: StatusCallback | None = None,
    profile: dict | None = None,
    roles: list[str] | None = None,
    continuous: bool = False,
    stop_event: threading.Event | None = None,
    batch_size: int | None = None,
    cooldown_seconds: int | None = None,
    cycle_callback: Callable[[int, list[dict]], None] | None = None,
    prioritize_remote: bool | None = None,
) -> dict[str, Any]:
    """Convenience entry point: build an agent and run the apply pipeline."""
    agent = ApplyAgent()
    return agent.run(
        query=query,
        resume_text=resume_text,
        resume_pdf=resume_pdf,
        portals=portals,
        mode=mode,
        max_applications=max_applications,
        on_status=on_status,
        profile=profile,
        roles=roles,
        continuous=continuous,
        stop_event=stop_event,
        batch_size=batch_size,
        cooldown_seconds=cooldown_seconds,
        cycle_callback=cycle_callback,
        prioritize_remote=prioritize_remote,
    )
