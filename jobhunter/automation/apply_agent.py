"""Semi-autonomous application agent for Naukri / Indeed (Google Jobs as fallback).

Modes:
- **human** (default): log in, find & score jobs, open the application, pre-fill
  the form, then leave submission to the user (needed for CAPTCHAs / multi-step
  ATS). The browser stays open so the user can finish.
- **auto**: additionally clicks submit automatically.
- **off**: does nothing.

Every portal is processed independently; failures, obstacles (CAPTCHAs, login
walls) and rate limits are caught, logged, and reported instead of crashing.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from jobhunter.agent import _default_llm
from jobhunter.automation import strategies
from jobhunter.automation.browser import BrowserSession, is_logged_in
from jobhunter.automation.evaluator import evaluate_job
from jobhunter.automation.form_filler import fill_form
from jobhunter.automation.profile import profile_from_resume
from jobhunter.automation.strategies import click_by_text, click_apply, fill_input
from jobhunter.config import Settings, get_settings
from jobhunter.core.history import save_applied_jobs

logger = logging.getLogger(__name__)

StatusCallback = Callable[[str, str, str], None]  # (level, stage, message)


class ApplyAgent:
    """Coordinates portal login, job discovery, evaluation, and applying."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._log: List[Dict[str, str]] = []
        self._on_status: Optional[StatusCallback] = None
        self._llm = None

    # ------------------------------------------------------------------ public
    def run(
        self,
        query: str,
        resume_text: str,
        portals: Optional[List[str]] = None,
        mode: Optional[str] = None,
        max_applications: Optional[int] = None,
        resume_pdf: Optional[str] = None,
        on_status: Optional[StatusCallback] = None,
    ) -> Dict[str, Any]:
        """Run the apply agent and return results + a log.

        ``mode`` defaults to ``auto_apply_mode`` from settings (``human``).
        """
        mode = mode or self.settings.auto_apply_mode
        max_applications = max_applications or self.settings.max_applications_per_run
        if mode == "off":
            self._report("info", "config", "Auto-apply is disabled (auto_apply_mode=off)")
            return {"results": [], "log": self._log, "mode": mode}

        portals = [p for p in (portals or ["naukri", "indeed"]) if p in strategies.PORTALS]
        profile = profile_from_resume(resume_text)
        self._on_status = on_status
        self._llm = _default_llm()

        if self.settings.fresher_only and not any(
            k in query.lower() for k in ("fresher", "entry level", "junior")
        ):
            query = f"{query} fresher"
            self._report("info", "start", f"Fresher mode on — search query set to '{query}'")

        self._report("info", "start", f"Mode={mode} | Portals={portals} | Max apps={max_applications}")
        self._report("info", "profile", f"Profile: {profile['email'] or 'no email'} | skills: {len(profile['skills'])}")

        results: List[Dict] = []
        session = BrowserSession(
            self.settings.browser_state_dir,
            self.settings.headless_browser,
            self.settings.browser_channel,
            self.settings.browser_use_default_profile,
            self.settings.browser_user_data_dir,
        )
        try:
            session.start()
            self._report(
                "info", "browser",
                "Using your default Chrome profile (existing logins reused). "
                if session.using_default_profile
                else "Using dedicated browser profile.",
            )
            for portal in portals:
                try:
                    outcomes = self._process_portal(
                        session, portal, query, resume_text, profile,
                        mode, max_applications, resume_pdf,
                    )
                    results.extend(outcomes)
                except Exception as exc:
                    logger.exception("Portal %s failed", portal)
                    self._report("error", portal, f"Failed: {exc}")

            # Fallback: nothing applied anywhere -> surface Google Jobs search.
            if not results:
                self._google_jobs_fallback(query, session)
                self._report("warning", "fallback", "No applications recorded; opened Google Jobs search for review.")
        finally:
            session.stop()

        return {"results": results, "log": self._log, "mode": mode}

    # ------------------------------------------------------------------ portals
    def _process_portal(
        self,
        session: BrowserSession,
        portal: str,
        query: str,
        resume_text: str,
        profile: Dict,
        mode: str,
        max_applications: int,
        resume_pdf: Optional[str],
    ) -> List[Dict]:
        config = strategies.PORTALS[portal]
        outcomes: List[Dict] = []
        page = session.new_page()

        if not self._ensure_login(page, portal):
            self._report("error", portal, "Login failed or credentials missing — skipping portal")
            return outcomes

        self._report("info", portal, f"Searching '{query}'")
        page.goto(strategies.build_search_url(portal, query), timeout=45000)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3500)

        obstacle = strategies.detect_obstacle(page.url, page.inner_text("body")[:4000])
        if obstacle:
            self._report(
                "warning", portal,
                f"Search blocked by a bot check ({obstacle}). You can complete it in "
                f"the browser window (the agent will continue after a refresh), or skip this portal.",
            )
            return outcomes

        jobs = strategies.collect_cards(page, portal, max_results=max(10, max_applications * 2))
        self._report("info", portal, f"{len(jobs)} jobs found")

        attempts = 0
        for job in jobs:
            if attempts >= max_applications:
                break

            if self.settings.fresher_only:
                required = strategies.job_experience_years(job)
                if required is not None and required > self.settings.max_experience_years:
                    self._report(
                        "info", portal,
                        f"Skipping {job['title']} @ {job['company']} — requires {required}+ yrs",
                    )
                    continue

            evaluation = evaluate_job(job, resume_text, self._llm)
            self._report(
                "info", portal,
                f"{job['title']} @ {job['company']} — {evaluation['decision']} ({evaluation['score']}%)",
            )
            if evaluation["decision"] != "apply":
                continue

            attempts += 1  # counts every apply attempt, keeping the run bounded
            outcome = self._apply_to_job(page, portal, job, profile, mode, resume_pdf)
            outcome["evaluation"] = evaluation
            outcomes.append(outcome)

            if outcome.get("status") in ("submitted", "handed_off"):
                self._record_application(resume_text, job, outcome)
                if mode == "human" and outcome.get("status") == "handed_off":
                    # Human-in-the-loop: pause so the user can finish the form.
                    self._report("info", portal, "Waiting 20s for you to complete the form in the browser window…")
                    time.sleep(20)

        return outcomes

    def _apply_to_job(
        self,
        page,
        portal: str,
        job: Dict,
        profile: Dict,
        mode: str,
        resume_pdf: Optional[str],
    ) -> Dict:
        config = strategies.PORTALS[portal]
        base = {"job_id": job["id"], "title": job["title"], "company": job["company"], "source": portal}

        try:
            page.goto(job["url"], timeout=45000)
        except Exception as exc:
            return {**base, "status": "failed", "detail": f"Could not open job page: {exc}"}
        page.wait_for_timeout(2500)

        obstacle = strategies.detect_obstacle(page.url, page.inner_text("body")[:4000])
        if obstacle:
            return {**base, "status": "blocked", "detail": f"Obstacle: {obstacle}"}

        clicked = strategies.click_apply(page)
        if not clicked:
            return {**base, "status": "no_apply_button", "detail": "No apply button found (maybe already applied or external ATS)."}

        page.wait_for_timeout(3000)
        stats = fill_form(page, profile, resume_pdf)

        if mode == "human":
            return {
                **base, "status": "handed_off",
                "detail": f"Form pre-filled ({stats['filled']} fields). Complete & submit in the browser window.",
                "filled_fields": stats,
            }

        submitted = (
            strategies.click_by_text(page, "Submit application")
            or strategies.click_by_text(page, "Submit")
            or strategies.click_by_text(page, "Submit now")
            or strategies.click_by_text(page, "Apply")
        )
        if submitted:
            return {**base, "status": "submitted", "detail": "Application submitted automatically.", "filled_fields": stats}
        return {**base, "status": "needs_review", "detail": "Form filled; submit button not found — complete manually.", "filled_fields": stats}

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
        login_url = strategies.PORTALS[portal]["login_url"].lower()
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

    def _google_jobs_fallback(self, query: str, session: BrowserSession) -> None:
        try:
            page = session.new_page()
            page.goto(strategies.build_search_url("google_jobs", query), timeout=45000)
            page.wait_for_timeout(2000)
        except Exception as exc:
            logger.warning("Google Jobs fallback failed: %s", exc)

    def _record_application(self, resume_text: str, job: Dict, outcome: Dict) -> None:
        try:
            save_applied_jobs(resume_text, [outcome["job_id"]], [{
                "job_id": outcome["job_id"],
                "title": job.get("title"),
                "company": job.get("company"),
                "source": job.get("source", job.get("portal")),
                "url": job.get("url", ""),
                "match_score": outcome.get("evaluation", {}).get("score"),
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


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat()


def run_application_pipeline(
    query: str,
    resume_text: str,
    resume_pdf: Optional[str] = None,
    portals: Optional[List[str]] = None,
    mode: Optional[str] = None,
    max_applications: Optional[int] = None,
    on_status: Optional[StatusCallback] = None,
) -> Dict[str, Any]:
    """Convenience entry point: build an agent and run the apply pipeline."""
    agent = ApplyAgent()
    return agent.run(
        query=query,
        resume_text=resume_text,
        portals=portals,
        mode=mode,
        max_applications=max_applications,
        resume_pdf=resume_pdf,
        on_status=on_status,
    )
