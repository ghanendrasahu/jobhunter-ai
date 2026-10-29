"""Streamlit page views: job search, auto apply, analytics, resumes, and settings."""

from __future__ import annotations

import os
import queue
import tempfile
import threading
from html import escape
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from jobhunter.agent import run_job_hunter
from jobhunter.automation import run_application_pipeline
from jobhunter.automation.candidate import build_candidate
from jobhunter.automation.profile import profile_from_resume
from jobhunter.automation.roles import suggest_roles, tier_display
from jobhunter.config import get_settings
from jobhunter.domains.candidate import Candidate
from jobhunter.domains.resume import extract_text_from_pdf
from jobhunter.domains.skills import family_display
from jobhunter.services.analytics import get_analytics_data
from jobhunter.storage.history import (
    delete_resume,
    export_history_csv,
    list_resumes,
    save_resume,
)
from jobhunter.storage.profiles import (
    load_candidate_knowledge,
    load_profile,
    load_selected_roles,
    load_suggested_roles,
    save_profile,
    save_selected_roles,
    save_suggested_roles,
)
from jobhunter.ui import design as ui
from jobhunter.ui.components import render_results

MAX_UPLOAD_MB = 10


@st.cache_data(show_spinner=False)
def _resume_text_cached(path: str, mtime: float, size: int) -> str:
    """Extract resume text, cached by file identity so reruns never re-parse."""
    return extract_text_from_pdf(path)


def _extract_resume_text(path: str) -> str:
    """Extract resume text, using the mtime/size-keyed cache for stable paths."""
    try:
        stat = os.stat(path)
        return _resume_text_cached(path, stat.st_mtime, stat.st_size)
    except OSError:
        return extract_text_from_pdf(path)


def job_search_page() -> None:
    """Upload/select a resume and run the pipeline."""
    ui.page_header(
        "Job Search",
        "Upload a resume to find matching roles in India, scored against your skills.",
        eyebrow="JobHunter AI",
        icon_name="search",
    )

    saved = list_resumes()
    resume_source = st.radio(
        "Resume source",
        ["Upload new PDF", "Use saved resume"],
        horizontal=True,
    )

    file_path = ""
    resume_source_is_upload = resume_source == "Upload new PDF"

    if resume_source_is_upload:
        uploaded = st.file_uploader("Choose a PDF resume", type=["pdf"])
        if uploaded:
            if uploaded.size > MAX_UPLOAD_MB * 1024 * 1024:
                st.error(f"Resume must be under {MAX_UPLOAD_MB} MB.")
                st.stop()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(uploaded.getvalue())
                tmp_path = tmp.name
            file_path = tmp_path
            st.success(f"{uploaded.name} uploaded ({uploaded.size / 1024:.0f} KB).")

            col1, col2 = st.columns([3, 1])
            with col2:
                name = st.text_input("Save as (optional)")
                if st.button("Save resume", width="stretch") and name:
                    save_resume(tmp_path, name)
                    st.rerun()
    else:
        if saved:
            resume_names = {f"{r['name']} ({r['id'][:8]})": r for r in saved}
            selected = st.selectbox("Select saved resume", list(resume_names.keys()))
            resume_meta = resume_names[selected]
            file_path = resume_meta["file_path"]
            if not Path(file_path).exists():
                ui.error_state(
                    "The saved copy of this resume is no longer on disk. Upload the PDF again to rebuild it.",
                    title="Resume file missing",
                    hint="Uploads are stored locally, so a moved workspace needs a fresh copy.",
                )
                st.stop()
            st.caption(
                f"Using {resume_meta['name']} - {resume_meta.get('applied_count', 0)} previous applications."
            )
        else:
            ui.empty_state(
                "No saved resumes yet",
                "Upload a PDF resume above. Saved resumes appear here for reuse.",
                icon_name="file",
            )

    if file_path and st.button("Run job search", type="primary", width="stretch"):
        with st.spinner("Searching portals and scoring matches..."):
            try:
                result = run_job_hunter(file_path)
            except Exception:
                ui.error_state(
                    "The resume could not be read, or the search stopped early. "
                    "Upload the PDF again and retry.",
                    title="The search could not finish",
                    hint="Your saved history is unchanged.",
                )
                st.stop()
            finally:
                if resume_source_is_upload:
                    try:
                        os.unlink(file_path)
                    except OSError:
                        pass

        ui.section("Results", "Matched roles, portal searches and submitted applications from this run.")
        render_results(result)
    elif not file_path:
        ui.empty_state(
            "No search run yet",
            "Choose a resume and select Run job search. Matched jobs, portal links and "
            "applications will appear here.",
            hint="PDF only, up to 10 MB.",
            icon_name="target",
        )
        st.markdown(
            '<div class="jh-features">'
            f'<div class="jh-feature">{ui.svg("target", 18)}'
            '<div class="jh-feature-title">Scored matches</div>'
            '<div class="jh-feature-body">Every role is ranked against your skills, with gaps called out.</div></div>'
            f'<div class="jh-feature">{ui.svg("search", 18)}'
            '<div class="jh-feature-title">Portal searches</div>'
            '<div class="jh-feature-body">Open the same query on Naukri, Indeed and more.</div></div>'
            f'<div class="jh-feature">{ui.svg("briefcase", 18)}'
            '<div class="jh-feature-title">Application tracking</div>'
            '<div class="jh-feature-body">See what was submitted, skipped or needs a manual step.</div></div>'
            "</div>",
            unsafe_allow_html=True,
        )


_PROFILE_FIELDS = [
    ("full_name", "Full name"),
    ("email", "Email"),
    ("phone", "Phone"),
    ("location", "Location"),
    ("current_title", "Current title / designation"),
    ("current_ctc", "Current CTC"),
    ("expected_ctc", "Expected CTC"),
    ("notice_period", "Notice period"),
    ("linkedin", "LinkedIn URL"),
    ("experience_years", "Experience (years)"),
]


def _status_label(level: str) -> str:
    """Plain-language label for a log level (no icons)."""
    return {"error": "Failed", "warning": "Attention", "info": "Update"}.get(level, "Update")


def _render_candidate_summary(data: dict) -> None:
    """Show a compact summary of the built candidate knowledge base."""
    candidate = Candidate.from_dict(data)
    family = family_display(candidate.role_family) if candidate.role_family else "Unknown"
    seniority = (
        candidate.seniority.replace("_", " ").title() if candidate.seniority != "UNKNOWN" else "Unknown"
    )
    years = candidate.experience_years if candidate.experience_years is not None else "Unknown"

    st.markdown(f"**Role family:** {family}")
    st.markdown(f"**Seniority:** {seniority} · **Experience:** {years} years")
    if candidate.skills:
        st.markdown("**Skills:** " + ", ".join(candidate.skills[:15]))
    if candidate.skill_groups:
        labels = " | ".join(f"{group}: {len(values)}" for group, values in candidate.skill_groups.items())
        st.markdown("**Skill groups:** " + labels)

    missing = sorted(
        {
            "full_name",
            "email",
            "phone",
            "location",
            "experience_years",
            "skills",
            "current_title",
            "notice_period",
        }
        - candidate.known_fields
    )
    if missing:
        st.caption("Not known yet (the agent will ask you later): " + ", ".join(missing))


def _run_agent_worker(
    status_queue: queue.Queue,
    stop_event: threading.Event,
    kwargs: dict,
) -> None:
    """Run the pipeline in a background thread, streaming status via a queue."""

    def on_status(level: str, stage: str, message: str) -> None:
        status_queue.put({"kind": "status", "level": level, "stage": stage, "message": message})

    try:
        result = run_application_pipeline(
            **kwargs,
            on_status=on_status,
            stop_event=stop_event,
        )
        status_queue.put({"kind": "done", "result": result})
    except Exception as exc:  # pragma: no cover - surfaced in the UI
        status_queue.put({"kind": "error", "message": str(exc)})


def auto_apply_page() -> None:
    """Continuous, interactive auto-apply agent (profile → roles → run)."""
    settings = get_settings()
    ui.page_header(
        "Auto Apply",
        "The agent reuses your existing Naukri and Indeed logins, searches the priority roles "
        "from your resume, and applies in batches until you stop it.",
        eyebrow="JobHunter AI",
        icon_name="bot",
    )

    step = st.radio(
        "Step",
        ["1. Resume & Profile", "2. Priority Roles", "3. Run"],
        horizontal=True,
        key="aa_step",
    )

    # ------------------------------------------------------------------ step 1
    if step.startswith("1"):
        ui.section(
            "Step 1 - Resume and profile", "Upload a resume and confirm the details the agent will reuse."
        )
        saved = list_resumes()
        resume_source = st.radio("Resume source", ["Upload new PDF", "Use saved resume"], horizontal=True)

        resume_text = ""
        resume_pdf: str | None = None
        if resume_source == "Upload new PDF":
            uploaded = st.file_uploader("Choose a PDF resume", type=["pdf"], key="aa_upload")
            if uploaded:
                if uploaded.size > MAX_UPLOAD_MB * 1024 * 1024:
                    st.error(f"Resume must be under {MAX_UPLOAD_MB} MB.")
                else:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(uploaded.getvalue())
                        resume_pdf = tmp.name
                    resume_text = extract_text_from_pdf(resume_pdf)
                    st.success(f"{uploaded.name} parsed - {len(resume_text):,} characters read.")
        elif saved:
            names = {f"{r['name']} ({r['id'][:8]})": r for r in saved}
            selected = st.selectbox("Select saved resume", list(names.keys()), key="aa_saved")
            resume_pdf = names[selected]["file_path"]
            try:
                resume_text = _extract_resume_text(resume_pdf)
            except OSError:
                ui.error_state(
                    "The saved copy of this resume is no longer on disk. Upload the PDF again to rebuild it.",
                    title="Resume file missing",
                    hint="Uploads are stored locally, so a moved workspace needs a fresh copy.",
                )
                st.stop()
        else:
            ui.empty_state(
                "No resume selected",
                "Upload a PDF resume above, or switch to a saved resume.",
                icon_name="file",
            )
            st.stop()

        if not resume_text:
            ui.empty_state(
                "Upload a resume to continue",
                "The agent reads your resume to build a profile and suggest roles. "
                "Add a PDF above, or pick a saved resume, to see the extracted details.",
                icon_name="upload",
            )
            st.stop()

        extracted = profile_from_resume(resume_text)
        prior = load_profile()
        st.caption(
            "Confirm the details extracted from your resume. Anything you change here overrides the extraction."
        )

        cols = st.columns(2)
        updated: dict = {}
        for i, (field, label) in enumerate(_PROFILE_FIELDS):
            with cols[i % 2]:
                updated[field] = st.text_input(
                    label,
                    value=prior.get(field) or extracted.get(field, ""),
                    key=f"pf_{field}",
                )
        skills = st.text_input(
            "Skills (comma-separated)",
            value=", ".join(prior.get("skills") or extracted.get("skills", [])),
            key="pf_skills",
        )
        updated["skills"] = [s.strip() for s in skills.split(",") if s.strip()]
        cover_letter = st.text_area(
            "Cover letter (optional — used when a form asks for one)",
            value=prior.get("cover_letter") or extracted.get("cover_letter", ""),
            height=120,
            key="pf_cover",
        )
        updated["cover_letter"] = cover_letter

        if st.button("Save profile", type="primary", width="stretch"):
            save_profile(updated)
            build_candidate(resume_text, profile=updated)
            st.session_state["aa_resume_text"] = resume_text
            st.session_state["aa_resume_pdf"] = resume_pdf
            st.session_state["aa_knowledge"] = load_candidate_knowledge()
            st.success("Profile saved. Continue to Step 2.")

        if st.session_state.get("aa_knowledge"):
            with st.expander("Candidate knowledge (auto-derived)"):
                _render_candidate_summary(st.session_state["aa_knowledge"])

    # ------------------------------------------------------------------ step 2
    elif step.startswith("2"):
        ui.section(
            "Step 2 - Priority roles",
            "Roles are ordered by fit. Select the ones the agent should search first.",
        )
        resume_text = st.session_state.get("aa_resume_text", "")
        if not resume_text:
            ui.empty_state(
                "Profile required",
                "Go back to Step 1 and save your profile before choosing roles.",
                icon_name="info",
            )
            st.stop()

        suggested = load_suggested_roles()
        if not suggested:
            with st.spinner("Analyzing your resume for suitable roles..."):
                suggested = suggest_roles(resume_text)
                save_suggested_roles(suggested)

        st.caption(
            "Priority data and AI roles are searched first. Select everything the agent should look for."
        )
        selected_roles: list[str] = []
        for tier in (1, 2, 3):
            tier_roles = [r for r in suggested if r["tier"] == tier]
            if not tier_roles:
                continue
            st.markdown(f"**{tier_display(tier)}**")
            options = {f"{r['title']} ({r['score'] * 100:.0f}%)": r["title"] for r in tier_roles}
            default_checked = [label for label, title in options.items() if tier == 1]
            prior_selected = set(load_selected_roles())
            picked = st.pills(
                "Roles",
                options=list(options.keys()),
                selection_mode="multi",
                default=default_checked,
                key=f"roles_tier_{tier}",
                label_visibility="collapsed",
            )
            for label in picked:
                selected_roles.append(options[label])

        # Merge with previously chosen roles that may not be in this resume's suggestions.
        for prior_role in prior_selected:
            if prior_role not in selected_roles:
                selected_roles.append(prior_role)

        if st.button("Save roles", type="primary", width="stretch"):
            save_selected_roles(selected_roles)
            st.session_state["aa_roles"] = selected_roles
            st.success(f"Saved {len(selected_roles)} roles. Continue to Step 3.")

    # ------------------------------------------------------------------ step 3
    else:
        ui.section("Step 3 - Run", "Choose how the agent applies, then start or stop the background run.")
        resume_text = st.session_state.get("aa_resume_text", "")
        if not resume_text:
            ui.empty_state(
                "Profile required",
                "Go back to Step 1 and save your profile before starting a run.",
                icon_name="info",
            )
            st.stop()

        roles = st.session_state.get("aa_roles") or load_selected_roles() or []
        profile = load_profile() or profile_from_resume(resume_text)

        col_l, col_r = st.columns([2, 1])
        with col_l:
            query = st.text_input(
                "Fallback search query (used when no roles are selected)",
                value="Python Developer",
                key="aa_query",
            )
            mode = st.selectbox(
                "Apply mode",
                ["human", "auto"],
                index=0 if settings.auto_apply_mode == "human" else 1,
                key="aa_mode",
                help="auto = submit filled forms (skips forms missing details); human = you submit each.",
            )
            portals = st.multiselect(
                "Portals", ["naukri", "indeed"], default=["naukri", "indeed"], key="aa_portals"
            )
        with col_r:
            batch_size = st.number_input(
                "Applications per cycle",
                min_value=1,
                max_value=20,
                value=int(settings.batch_size),
                key="aa_batch",
            )
            cooldown = st.number_input(
                "Cooldown between cycles (seconds)",
                min_value=0,
                max_value=3600,
                value=int(settings.cooldown_seconds),
                step=30,
                key="aa_cooldown",
            )
            continuous = st.checkbox(
                "Keep running until I press Stop",
                value=True,
                key="aa_continuous",
                help="Runs cycle after cycle, rotating roles, until you stop it.",
            )
            prioritize_remote = st.checkbox(
                "Prioritize work-from-home roles", value=settings.prioritize_remote, key="aa_remote"
            )

        if roles:
            more = " and more" if len(roles) > 8 else ""
            st.caption("Searching: " + ", ".join(roles[:8]) + more + ".")

        with st.expander("JobHunter Browser"):
            from jobhunter.automation.browser import (
                PORTAL_LOGIN_CHECKS,
                browser_status,
                check_portal_logins,
                detect_chrome_user_data_dir,
                is_chrome_running,
                launch_dedicated_browser,
                list_chrome_profiles,
                open_login_page,
            )

            status = browser_status(settings)
            if status["running"]:
                st.success("Browser connected. Portal logins are reused from this window.")
            else:
                st.info("Browser not connected. Launch it once and log in to each portal.")

            col_b_l, col_b_r = st.columns([1, 1])
            with col_b_l:
                if st.button("Connect browser", width="stretch"):
                    try:
                        st.success(launch_dedicated_browser(settings))
                    except Exception as exc:
                        st.error(f"Could not start the JobHunter browser: {exc}")
            with col_b_r:
                if st.button("Check logins", width="stretch"):
                    with st.spinner("Checking Naukri / LinkedIn / Indeed in the JobHunter window…"):
                        try:
                            for portal, logged_in in check_portal_logins(settings).items():
                                mark = "logged in" if logged_in else "not logged in"
                                st.write(f"- **{portal.capitalize()}:** {mark}")
                        except Exception as exc:
                            st.error(f"Login check failed: {exc}")

            st.caption("Log in once per portal in the opened window. Later runs reuse that session.")
            login_cols = st.columns(len(PORTAL_LOGIN_CHECKS))
            for col, portal in zip(login_cols, PORTAL_LOGIN_CHECKS, strict=True):
                with col:
                    url = PORTAL_LOGIN_CHECKS[portal][0]
                    if st.button(f"Log in to {portal.capitalize()}", width="stretch"):
                        try:
                            st.success(open_login_page(settings, url))
                        except Exception as exc:
                            st.error(f"Could not open {portal}: {exc}")

            with st.expander("Your real Chrome profiles (information only)"):
                ud = detect_chrome_user_data_dir()
                if ud is None:
                    st.write("Chrome profile directory not detected.")
                else:
                    st.write(f"User data directory: `{ud}`")
                    st.write(
                        "Any Chrome process running now (includes the JobHunter window): "
                        + ("**yes**" if is_chrome_running() else "no")
                    )
                    profiles = list_chrome_profiles(ud)
                    if profiles:
                        st.write("Detected profiles:")
                        for info in profiles:
                            label = info.friendly_name or info.dir_name
                            st.write(f"- `{info.dir_name}` → **{label}**")
                    st.warning(
                        "Chrome 136+ blocks automated control of your real Chrome profile "
                        "(security fix), and its cookies are encrypted (App-Bound Encryption), "
                        "so logins cannot be copied into JobHunter. Your real profiles are never "
                        "touched or closed — JobHunter uses its own separate window, where you log "
                        "in once per portal."
                    )

        status_queue_raw = st.session_state.get("aa_queue")
        status_queue: queue.Queue | None = (
            status_queue_raw if isinstance(status_queue_raw, queue.Queue) else None
        )
        stop_event: threading.Event | None = st.session_state.get("aa_stop")
        thread: threading.Thread | None = st.session_state.get("aa_thread")
        running = thread is not None and thread.is_alive()

        col_b1, col_b2, col_b3 = st.columns([1, 1, 1])
        with col_b1:
            if st.button("Start applying", type="primary", width="stretch", disabled=running):
                q: queue.Queue = queue.Queue()
                ev = threading.Event()
                kwargs = {
                    "query": query,
                    "resume_text": resume_text,
                    "resume_pdf": st.session_state.get("aa_resume_pdf"),
                    "portals": portals or None,
                    "mode": mode,
                    "profile": profile,
                    "roles": roles or None,
                    "continuous": continuous,
                    "batch_size": int(batch_size),
                    "cooldown_seconds": int(cooldown),
                    "max_applications": int(batch_size),
                    "prioritize_remote": prioritize_remote,
                }
                t = threading.Thread(target=_run_agent_worker, args=(q, ev, kwargs), daemon=True)
                t.start()
                st.session_state["aa_queue"] = q
                st.session_state["aa_stop"] = ev
                st.session_state["aa_thread"] = t
                st.session_state["aa_log"] = []
                st.session_state["aa_done"] = None
                st.rerun()
        with col_b2:
            if st.button("Stop", width="stretch", disabled=not running):
                if stop_event:
                    stop_event.set()
                st.rerun()
        with col_b3:
            if st.button("Reset", width="stretch", disabled=running):
                for key in ("aa_queue", "aa_stop", "aa_thread", "aa_log", "aa_done"):
                    st.session_state.pop(key, None)
                st.rerun()

        if running:
            st.info("The agent is running. Log lines refresh as new events arrive.")

        log: list[dict] = st.session_state.get("aa_log", [])
        done_result = st.session_state.get("aa_done")
        if status_queue is not None:
            drain = True
            while drain:
                try:
                    entry = status_queue.get_nowait()
                    if entry["kind"] == "status":
                        log.append(entry)
                    elif entry["kind"] == "done":
                        st.session_state["aa_done"] = entry["result"]
                        done_result = entry["result"]
                    elif entry["kind"] == "error":
                        log.append({"level": "error", "stage": "run", "message": entry["message"]})
                except queue.Empty:
                    drain = False
            st.session_state["aa_log"] = log[-400:]

        if log:
            with st.expander("Live agent log", expanded=True):
                for entry in log:
                    stage = str(entry["stage"]).replace("_", " ").title()
                    st.markdown(f"**{_status_label(entry['level'])}** - {stage}: {entry['message']}")

        if done_result is not None:
            results = done_result.get("results", [])
            cycles = done_result.get("cycles", 1)
            ui.section(
                "Outcome",
                f"Completed {cycles} cycles with {len(results)} application attempts.",
            )
            if results:
                df = pd.DataFrame(
                    [
                        {
                            "Title": r.get("title"),
                            "Company": r.get("company"),
                            "Source": r.get("source"),
                            "Status": r.get("status"),
                            "Score": r.get("evaluation", {}).get("score"),
                        }
                        for r in results
                    ]
                )
                st.dataframe(df, width="stretch", hide_index=True)
                needs_help = [
                    r for r in results if r.get("status") in ("needs_review", "blocked", "no_apply_button")
                ]
                if needs_help:
                    ui.section(
                        "Needs your help",
                        "These applications stopped before submission and need a manual step.",
                    )
                    for r in needs_help:
                        st.markdown(f"- **{r.get('title')}** at {r.get('company')} - {r.get('detail')}")
            else:
                ui.empty_state(
                    "No applications attempted",
                    "Nothing was submitted this run. Missing credentials or a blocked portal "
                    "are the usual causes.",
                    icon_name="alert",
                )


def dashboard_page() -> None:
    """Analytics dashboard."""
    ui.page_header(
        "Analytics",
        "Application activity across every resume and portal.",
        eyebrow="JobHunter AI",
        icon_name="chart",
    )
    data = get_analytics_data()

    avg_per_day = sum(data["daily_counts"].values()) / max(len(data["daily_counts"]), 1)
    ui.metric_grid(
        [
            {"label": "Total applications", "value": f"{data['total_applied']:,}"},
            {"label": "Resumes used", "value": f"{data['total_resumes']:,}"},
            {"label": "Unique jobs", "value": f"{data['unique_jobs']:,}"},
            {"label": "Average per day", "value": f"{avg_per_day:.1f}", "caption": "on active days"},
        ]
    )

    col_a, col_b = st.columns(2)

    with col_a:
        ui.section("Applications by source")
        if data["source_counts"]:
            df = pd.DataFrame(list(data["source_counts"].items()), columns=["Source", "Count"])
            fig = px.pie(df, values="Count", names="Source", hole=0.45)
            ui.style_fig(fig, height=300)
            st.plotly_chart(fig, width="stretch")
        else:
            ui.empty_state(
                "No source data yet",
                "Run a job search to record where applications came from.",
                icon_name="database",
            )

    with col_b:
        ui.section("Applications over time")
        if data["daily_counts"]:
            df = pd.DataFrame(list(data["daily_counts"].items()), columns=["Date", "Count"])
            fig = px.line(
                df,
                x="Date",
                y="Count",
                markers=True,
                color_discrete_sequence=[ui.PRIMARY],
            )
            ui.style_fig(fig, height=300)
            fig.update_layout(xaxis_title=None, yaxis_title=None)
            st.plotly_chart(fig, width="stretch")
        else:
            ui.empty_state(
                "No activity yet",
                "Application dates appear here once the agent submits its first batch.",
                icon_name="clock",
            )

    ui.section("Top companies")
    if data["top_companies"]:
        df = pd.DataFrame(list(data["top_companies"].items()), columns=["Company", "Applications"])
        fig = px.bar(
            df,
            x="Applications",
            y="Company",
            orientation="h",
            color_discrete_sequence=[ui.PRIMARY],
        )
        ui.style_fig(fig, height=400)
        fig.update_layout(xaxis_title=None, yaxis_title=None)
        st.plotly_chart(fig, width="stretch")
    else:
        ui.empty_state(
            "No companies yet",
            "Companies you apply to will be ranked here by application volume.",
            icon_name="briefcase",
        )


def resumes_page() -> None:
    """Manage saved resumes and re-run the pipeline on them."""
    ui.page_header(
        "Saved Resumes",
        "Reuse a stored resume, preview what the agent reads, or start a new search.",
        eyebrow="JobHunter AI",
        icon_name="file",
    )

    saved = list_resumes()
    if saved:
        for res in saved:
            col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
            with col1:
                st.markdown(
                    f'<div class="jh-resume">'
                    f'<div class="jh-resume-name">{escape(str(res["name"]))}</div>'
                    f'<div class="jh-job-meta">Saved {escape(str(res.get("created_at", ""))[:10])}'
                    f" · {res.get('applied_count', 0)} applications</div></div>",
                    unsafe_allow_html=True,
                )
            with col2:
                if st.button("Preview", key=f"view_{res['id']}", width="stretch"):
                    st.info((res.get("text") or "No text stored for this resume.")[:300])
            with col3:
                if st.button("Run", key=f"run_{res['id']}", width="stretch"):
                    st.session_state["run_resume_path"] = res["file_path"]
                    st.rerun()
            with col4:
                if st.button("Delete", key=f"del_{res['id']}", width="stretch"):
                    delete_resume(res["id"])
                    st.rerun()
        st.caption(
            "Preview shows the text the agent reads. Delete removes the saved copy; "
            "application history is kept."
        )
    else:
        ui.empty_state(
            "No saved resumes yet",
            "Upload a resume on the Job Search page and save it to reuse it here.",
            icon_name="file",
        )

    run_path = st.session_state.pop("run_resume_path", None)
    if run_path:
        ui.section("Results", "Search results for the selected resume.")
        with st.spinner("Searching portals and scoring matches..."):
            try:
                render_results(run_job_hunter(run_path))
            except Exception:
                ui.error_state(
                    "The resume file could not be read. Upload it again, then run the search.",
                    title="The search could not finish",
                    hint="Your saved history is unchanged.",
                )


def settings_page() -> None:
    """Edit portal credentials, preferences, and email config (persisted)."""
    ui.page_header(
        "Settings",
        "Credentials and defaults used by the apply agent. Saved values override the local environment file.",
        eyebrow="JobHunter AI",
        icon_name="sliders",
    )

    settings = get_settings()
    from jobhunter.storage.settings import load_settings, save_settings

    saved = load_settings()
    changed: dict[str, str] = {}

    with st.expander("Portal credentials", expanded=True):
        naukri_email = st.text_input(
            "Naukri email",
            value=saved.get("naukri_email", settings.naukri_email),
            key="set_naukri_email",
        )
        naukri_password = st.text_input(
            "Naukri password",
            value=saved.get("naukri_password", settings.naukri_password),
            type="password",
            key="set_naukri_password",
        )
        indeed_email = st.text_input(
            "Indeed email",
            value=saved.get("indeed_email", settings.indeed_email),
            key="set_indeed_email",
        )
        indeed_password = st.text_input(
            "Indeed password",
            value=saved.get("indeed_password", settings.indeed_password),
            type="password",
            key="set_indeed_password",
        )
        st.caption(
            "Tip: if you log in via Google, leave these blank — JobHunter reuses your Chrome login instead."
        )
        changed.update(
            {
                "naukri_email": naukri_email,
                "naukri_password": naukri_password,
                "indeed_email": indeed_email,
                "indeed_password": indeed_password,
            }
        )

    with st.expander("Application preferences"):
        _modes = ["human", "auto", "off"]
        _current_mode = saved.get("auto_apply_mode", settings.auto_apply_mode)
        _mode_index = _modes.index(_current_mode) if _current_mode in _modes else 0
        auto_apply_mode = st.selectbox(
            "Auto-apply mode",
            options=_modes,
            index=_mode_index,
            key="set_mode",
        )
        max_applications = st.slider(
            "Max applications per run",
            min_value=1,
            max_value=20,
            value=int(saved.get("max_applications_per_run", settings.max_applications_per_run)),
            key="set_max_apps",
        )
        changed.update(
            {
                "auto_apply_mode": auto_apply_mode,
                "max_applications_per_run": str(max_applications),
            }
        )

    with st.expander("Email notifications"):
        st.caption("For Gmail, use an App Password (not your regular password).")
        smtp_host = st.text_input(
            "SMTP host",
            value=saved.get("smtp_host", settings.smtp_host),
            key="set_smtp_host",
        )
        smtp_port = st.number_input(
            "SMTP port",
            min_value=1,
            max_value=65535,
            value=int(saved.get("smtp_port", settings.smtp_port)),
            key="set_smtp_port",
        )
        smtp_user = st.text_input(
            "SMTP user",
            value=saved.get("smtp_user", settings.smtp_user),
            key="set_smtp_user",
        )
        smtp_pass = st.text_input(
            "SMTP password",
            value=saved.get("smtp_pass", settings.smtp_pass),
            type="password",
            key="set_smtp_pass",
        )
        notification_email = st.text_input(
            "Notification email",
            value=saved.get("notification_email", settings.notification_email),
            key="set_notif_email",
        )
        changed.update(
            {
                "smtp_host": smtp_host,
                "smtp_port": str(int(smtp_port)),
                "smtp_user": smtp_user,
                "smtp_pass": smtp_pass,
                "notification_email": notification_email,
            }
        )

    if st.button("Save settings", type="primary", width="stretch"):
        save_settings({k: v for k, v in changed.items() if v != saved.get(k, "")})
        st.success("Settings saved. They apply on the next pipeline run.")
        st.rerun()

    with st.expander("Export data"):
        st.caption("Download every application recorded by this workspace as a CSV file.")
        csv_data = export_history_csv()
        st.download_button(
            "Download history CSV",
            data=csv_data,
            file_name="jobhunter_complete_history.csv",
            mime="text/csv",
            width="stretch",
        )
