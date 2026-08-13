"""Streamlit page views: job search, auto apply, analytics, resumes, and settings."""

from __future__ import annotations

import os
import queue
import tempfile
import threading
import time
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from jobhunter.agent import run_job_hunter
from jobhunter.automation import run_application_pipeline
from jobhunter.automation.profile import profile_from_resume
from jobhunter.automation.roles import suggest_roles, tier_display
from jobhunter.config import get_settings
from jobhunter.domains.resume import extract_text_from_pdf
from jobhunter.services.analytics import get_analytics_data
from jobhunter.storage.history import (
    delete_resume,
    export_history_csv,
    list_all_histories,
    list_resumes,
    save_resume,
)
from jobhunter.storage.profiles import (
    load_profile,
    load_selected_roles,
    load_suggested_roles,
    save_profile,
    save_selected_roles,
    save_suggested_roles,
)
from jobhunter.ui.components import render_results

MAX_UPLOAD_MB = 10


def job_search_page() -> None:
    """Upload/select a resume and run the pipeline."""
    st.markdown("## 🎯 Job Search")
    st.markdown("Upload your resume to find matching Indian jobs with AI-powered scoring.")

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
                st.error(f"Max {MAX_UPLOAD_MB} MB")
                st.stop()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(uploaded.getvalue())
                tmp_path = tmp.name
            file_path = tmp_path
            st.success(f"✅ {uploaded.name} ({uploaded.size / 1024:.0f} KB)")

            col1, col2 = st.columns([3, 1])
            with col2:
                name = st.text_input("Save as (optional)")
                if st.button("💾 Save Resume", use_container_width=True) and name:
                    save_resume(tmp_path, name)
                    st.rerun()
    else:
        if saved:
            resume_names = {f"{r['name']} ({r['id'][:8]})": r for r in saved}
            selected = st.selectbox("Select saved resume", list(resume_names.keys()))
            resume_meta = resume_names[selected]
            file_path = resume_meta["file_path"]
            st.info(f"📄 {resume_meta['name']} — {resume_meta.get('applied_count', 0)} previous applications")
        else:
            st.warning("No saved resumes. Upload one first.")

    if file_path and st.button("🚀 Run Job Hunter Pipeline", type="primary", use_container_width=True):
        with st.spinner("Running pipeline..."):
            bar = st.progress(0, text="Extracting resume...")
            try:
                steps = [
                    (10, "Extracting text from PDF..."),
                    (25, "Generating search query..."),
                    (50, "Scraping Indeed, LinkedIn, Naukri..."),
                    (70, "Scoring jobs against your resume..."),
                    (90, "Recording applications..."),
                    (100, "Done!"),
                ]
                for pct, msg in steps:
                    time.sleep(0.3)
                    bar.progress(pct, text=msg)

                result = run_job_hunter(file_path)
                bar.empty()
            except Exception as exc:
                bar.empty()
                st.error(f"Pipeline failed: {exc}")
                st.stop()
            finally:
                if resume_source_is_upload:
                    try:
                        os.unlink(file_path)
                    except OSError:
                        pass

        st.markdown("---")
        st.markdown("## 📊 Results")
        render_results(result)


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


def _status_icon(level: str) -> str:
    return {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(level, "ℹ️")


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
    st.markdown("## 🤖 Auto Apply Agent")
    st.markdown(
        "The agent uses **your existing Chrome logins** (Naukri/Indeed), searches based on "
        "**priority roles** from your resume (AI/ML/Data/Analyst first), and applies in "
        "batches — pausing between cycles until you press **Stop**."
    )

    step = st.radio(
        "Step",
        ["1. Resume & Profile", "2. Priority Roles", "3. Run"],
        horizontal=True,
        key="aa_step",
    )

    # ------------------------------------------------------------------ step 1
    if step.startswith("1"):
        st.markdown("### 📄 Step 1 — Resume & Profile")
        saved = list_resumes()
        resume_source = st.radio("Resume source", ["Upload new PDF", "Use saved resume"], horizontal=True)

        resume_text = ""
        resume_pdf: str | None = None
        if resume_source == "Upload new PDF":
            uploaded = st.file_uploader("Choose a PDF resume", type=["pdf"], key="aa_upload")
            if uploaded:
                if uploaded.size > MAX_UPLOAD_MB * 1024 * 1024:
                    st.error(f"Max {MAX_UPLOAD_MB} MB")
                else:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(uploaded.getvalue())
                        resume_pdf = tmp.name
                    resume_text = extract_text_from_pdf(resume_pdf)
                    st.success(f"✅ {uploaded.name} parsed ({len(resume_text)} chars)")
        elif saved:
            names = {f"{r['name']} ({r['id'][:8]})": r for r in saved}
            selected = st.selectbox("Select saved resume", list(names.keys()), key="aa_saved")
            resume_pdf = names[selected]["file_path"]
            resume_text = extract_text_from_pdf(resume_pdf)
        else:
            st.warning("No saved resumes. Upload one first.")

        if not resume_text:
            st.stop()

        extracted = profile_from_resume(resume_text)
        prior = load_profile()
        st.caption("Confirm or correct the details extracted from your resume. Missing values are filled automatically with what you enter here.")

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

        if st.button("💾 Save Profile", type="primary"):
            save_profile(updated)
            st.session_state["aa_resume_text"] = resume_text
            st.session_state["aa_resume_pdf"] = resume_pdf
            st.success("Profile saved. Continue to Step 2.")

    # ------------------------------------------------------------------ step 2
    elif step.startswith("2"):
        st.markdown("### ⭐ Step 2 — Priority Roles")
        resume_text = st.session_state.get("aa_resume_text", "")
        if not resume_text:
            st.warning("Go back to Step 1 and save your profile first.")
            st.stop()

        suggested = load_suggested_roles()
        if not suggested:
            with st.spinner("Analyzing your resume for suitable roles..."):
                suggested = suggest_roles(resume_text)
                save_suggested_roles(suggested)

        st.caption("⭐ Priority (AI/ML/Data/Analyst) roles are searched first. Select what you want the agent to look for.")
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

        if st.button("💾 Save Roles", type="primary"):
            save_selected_roles(selected_roles)
            st.session_state["aa_roles"] = selected_roles
            st.success(f"Saved {len(selected_roles)} role(s). Continue to Step 3.")

    # ------------------------------------------------------------------ step 3
    else:
        st.markdown("### 🚀 Step 3 — Run")
        resume_text = st.session_state.get("aa_resume_text", "")
        if not resume_text:
            st.warning("Go back to Step 1 and save your profile first.")
            st.stop()

        roles = st.session_state.get("aa_roles") or load_selected_roles() or []
        profile = load_profile() or profile_from_resume(resume_text)

        col_l, col_r = st.columns([2, 1])
        with col_l:
            query = st.text_input("🔍 Fallback search query (used when no roles are selected)", value="Python Developer", key="aa_query")
            mode = st.selectbox("Apply mode", ["human", "auto"], index=0 if settings.auto_apply_mode == "human" else 1, key="aa_mode",
                                help="auto = submit filled forms (skips forms missing details); human = you submit each.")
            portals = st.multiselect("Portals", ["naukri", "indeed"], default=["naukri", "indeed"], key="aa_portals")
        with col_r:
            batch_size = st.number_input("Applications per cycle", min_value=1, max_value=20, value=int(settings.batch_size), key="aa_batch")
            cooldown = st.number_input("Cooldown between cycles (seconds)", min_value=0, max_value=3600, value=int(settings.cooldown_seconds), step=30, key="aa_cooldown")
            continuous = st.checkbox("Keep running until I press Stop", value=True, key="aa_continuous",
                                     help="Runs cycle after cycle, rotating roles, until you stop it.")
            prioritize_remote = st.checkbox("Prioritize work-from-home roles", value=settings.prioritize_remote, key="aa_remote")

        if roles:
            st.info(f"Searching priority roles: **{', '.join(roles[:8])}**" + ("…" if len(roles) > 8 else ""))

        status_queue_raw = st.session_state.get("aa_queue")
        status_queue: queue.Queue | None = status_queue_raw if isinstance(status_queue_raw, queue.Queue) else None
        stop_event: threading.Event | None = st.session_state.get("aa_stop")
        thread: threading.Thread | None = st.session_state.get("aa_thread")
        running = thread is not None and thread.is_alive()

        col_b1, col_b2, col_b3 = st.columns([1, 1, 1])
        with col_b1:
            if st.button("▶️ Start", type="primary", use_container_width=True, disabled=running):
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
            if st.button("⏹ Stop", use_container_width=True, disabled=not running):
                if stop_event:
                    stop_event.set()
                st.rerun()
        with col_b3:
            if st.button("🧹 Reset", use_container_width=True, disabled=running):
                for key in ("aa_queue", "aa_stop", "aa_thread", "aa_log", "aa_done"):
                    st.session_state.pop(key, None)
                st.rerun()

        if running:
            st.warning("Agent is running in the background. New log lines appear as they arrive — wait a moment and the list refreshes on the next interaction.")

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
            with st.expander("📜 Live Agent Log", expanded=True):
                for entry in log:
                    st.markdown(f"{_status_icon(entry['level'])} `{entry['stage']}` — {entry['message']}")

        if done_result is not None:
            results = done_result.get("results", [])
            cycles = done_result.get("cycles", 1)
            st.markdown("## 📋 Outcome")
            st.caption(f"Completed {cycles} cycle(s) — {len(results)} application attempt(s).")
            if results:
                df = pd.DataFrame([
                    {
                        "Title": r.get("title"),
                        "Company": r.get("company"),
                        "Source": r.get("source"),
                        "Status": r.get("status"),
                        "Score": r.get("evaluation", {}).get("score"),
                    }
                    for r in results
                ])
                st.dataframe(df, use_container_width=True)
                for r in results:
                    st.markdown(f"- **{r.get('title')}** @ {r.get('company')} → `{r.get('status')}` — {r.get('detail')}")
                needs_help = [r for r in results if r.get("status") in ("needs_review", "blocked", "no_apply_button")]
                if needs_help:
                    st.markdown("### 🤝 Needs your help")
                    for r in needs_help:
                        st.markdown(f"- ❌ **{r.get('title')}** @ {r.get('company')} — {r.get('detail')}")
            else:
                st.warning("No applications attempted. Check the log above (likely missing credentials or blocked).")


def dashboard_page() -> None:
    """Analytics dashboard."""
    st.markdown("## 📊 Analytics Dashboard")
    data = get_analytics_data()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Applications", data["total_applied"])
    col2.metric("Resumes Used", data["total_resumes"])
    col3.metric("Unique Jobs", data["unique_jobs"])
    col4.metric("Avg/Day", f"{sum(data['daily_counts'].values()) / max(len(data['daily_counts']), 1):.1f}")

    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("Applications by Source")
        if data["source_counts"]:
            df = pd.DataFrame(list(data["source_counts"].items()), columns=["Source", "Count"])
            fig = px.pie(df, values="Count", names="Source", hole=0.4)
            fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data yet")

    with col_b:
        st.subheader("Applications Over Time")
        if data["daily_counts"]:
            df = pd.DataFrame(list(data["daily_counts"].items()), columns=["Date", "Count"])
            fig = px.line(df, x="Date", y="Count", markers=True)
            fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data yet")

    st.subheader("Top Companies")
    if data["top_companies"]:
        df = pd.DataFrame(list(data["top_companies"].items()), columns=["Company", "Applications"])
        fig = px.bar(df, x="Applications", y="Company", orientation="h")
        fig.update_layout(height=400, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data yet")


def resumes_page() -> None:
    """Manage saved resumes and re-run the pipeline on them."""
    st.markdown("## 📝 Saved Resumes")

    saved = list_resumes()
    if saved:
        for res in saved:
            col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
            with col1:
                st.markdown(
                    f'<div class="resume-card">'
                    f'<strong>{res["name"]}</strong><br>'
                    f'<span style="font-size:0.8rem; color:#6c757d;">'
                    f'ID: {res["id"][:8]} | Applied: {res.get("applied_count", 0)} jobs | '
                    f'Created: {res.get("created_at", "")[:10]}'
                    f"</span></div>",
                    unsafe_allow_html=True,
                )
            with col2:
                if st.button("📄 View", key=f"view_{res['id']}"):
                    st.info(f"Preview: {res.get('text', 'N/A')[:300]}...")
            with col3:
                if st.button("🚀 Run", key=f"run_{res['id']}"):
                    st.session_state["run_resume_path"] = res["file_path"]
                    st.rerun()
            with col4:
                if st.button("🗑️", key=f"del_{res['id']}"):
                    delete_resume(res["id"])
                    st.rerun()
    else:
        st.info("No saved resumes. Upload one in the Job Search tab.")

    run_path = st.session_state.pop("run_resume_path", None)
    if run_path:
        st.markdown("## 📊 Results")
        with st.spinner("Running pipeline..."):
            try:
                render_results(run_job_hunter(run_path))
            except Exception as exc:
                st.error(f"Pipeline failed: {exc}")


def settings_page() -> None:
    """Edit portal credentials, preferences, and email config (persisted)."""
    st.markdown("## ⚙️ Settings")
    st.caption("Saved settings are stored locally and layered over your `.env` file.")

    settings = get_settings()
    from jobhunter.storage.settings import load_settings, save_settings

    saved = load_settings()
    changed: dict[str, str] = {}

    with st.expander("🔑 Portal Credentials", expanded=True):
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
            "Tip: if you log in via Google, leave these blank — JobHunter reuses "
            "your Chrome login instead."
        )
        changed.update({
            "naukri_email": naukri_email,
            "naukri_password": naukri_password,
            "indeed_email": indeed_email,
            "indeed_password": indeed_password,
        })

    with st.expander("⚡ Application Preferences"):
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
        changed.update({
            "auto_apply_mode": auto_apply_mode,
            "max_applications_per_run": str(max_applications),
        })

    with st.expander("📧 Email Notifications"):
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
        changed.update({
            "smtp_host": smtp_host,
            "smtp_port": str(int(smtp_port)),
            "smtp_user": smtp_user,
            "smtp_pass": smtp_pass,
            "notification_email": notification_email,
        })

    if st.button("💾 Save Settings", type="primary"):
        save_settings({k: v for k, v in changed.items() if v != saved.get(k, "")})
        st.success("Settings saved. They apply on the next pipeline run.")
        st.rerun()

    with st.expander("📤 Export All Data"):
        csv_data = export_history_csv()
        st.download_button(
            "📥 Download Complete History CSV",
            data=csv_data,
            file_name="jobhunter_complete_history.csv",
            mime="text/csv",
        )

        st.markdown("### Debug Info")
        histories = list_all_histories()
        st.json({
            "total_histories": len(histories),
            "total_applied": sum(len(h.get("applied_job_ids", [])) for h in histories),
            "resumes_dir": str(Path("resumes").absolute()),
            "history_dir": str(Path("history").absolute()),
        })
