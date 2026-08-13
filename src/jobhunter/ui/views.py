"""Streamlit page views: job search, auto apply, analytics, resumes, and settings."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from jobhunter.agent import run_job_hunter
from jobhunter.automation import run_application_pipeline
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


def auto_apply_page() -> None:
    """Semi-autonomous application agent (Naukri / Indeed / Google Jobs)."""
    settings = get_settings()
    st.markdown("## 🤖 Auto Apply Agent")
    st.markdown(
        "The agent logs into your portals, finds jobs, scores them against your resume "
        "with AI, and fills application forms. **Human mode** pre-fills and lets you "
        "click submit (handles CAPTCHAs); **auto mode** submits automatically."
    )

    col_left, col_right = st.columns([2, 1])
    with col_left:
        query = st.text_input("🔍 Search query", value="Python Developer")
        saved = list_resumes()
        resume_source = st.radio("Resume source", ["Upload new PDF", "Use saved resume"], horizontal=True)

        resume_text = ""
        resume_pdf = None
        if resume_source == "Upload new PDF":
            uploaded = st.file_uploader("Choose a PDF resume", type=["pdf"])
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
            selected = st.selectbox("Select saved resume", list(names.keys()))
            resume_pdf = names[selected]["file_path"]
            resume_text = extract_text_from_pdf(resume_pdf)

        with st.expander("⚙️ Agent settings"):
            mode = st.selectbox("Apply mode", ["human", "auto", "off"],
                                index=["human", "auto", "off"].index(settings.auto_apply_mode))
            portals = st.multiselect("Portals", ["naukri", "indeed"], default=["naukri", "indeed"])
            max_apps = st.slider("Max applications per run", 1, 10, settings.max_applications_per_run)
            st.caption("No portal passwords needed: leave `.env` credentials empty and log in once in the opened browser window (session persists).")

    with col_right:
        st.markdown("#### Apply from your account → confirmation emails")
        st.markdown("Two ways (either gives you real confirmation emails):")
        st.markdown("1. **`.env` credentials** — `NAUKRI_EMAIL/NAUKRI_PASSWORD`, `INDEED_EMAIL/INDEED_PASSWORD`. Auto-login via the portal's own form (no Google block). Emails go to that account's email.")
        st.markdown("2. **Default-Chrome sessions** — your existing logins are reused automatically (copied profile).")

    if resume_text and st.button("🚀 Run Apply Agent", type="primary", use_container_width=True):
        with st.status("Running apply agent…", expanded=True) as status:
            status_log: dict[str, str] = {}

            def on_status(level: str, stage: str, message: str) -> None:
                status_log[f"{stage}"] = message
                icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(level, "ℹ️")
                st.write(f"{icon} **{stage.title()}:** {message}")

            result = run_application_pipeline(
                query=query,
                resume_text=resume_text,
                resume_pdf=resume_pdf,
                portals=portals or None,
                mode=mode,
                max_applications=max_apps,
                on_status=on_status,
            )
            status.update(label="Apply agent finished", state="complete")

        results = result.get("results", [])
        st.markdown("## 📋 Outcome")
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
        else:
            st.warning("No applications attempted. Check the log above (likely missing credentials or blocked).")

        with st.expander("🔎 Agent log"):
            for entry in result.get("log", []):
                icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(entry["level"], "ℹ️")
                st.write(f"{icon} `{entry['stage']}` — {entry['message']}")

        if resume_source == "Upload new PDF" and resume_pdf:
            try:
                os.unlink(resume_pdf)
            except OSError:
                pass


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
    """Configuration reference and data export."""
    st.markdown("## ⚙️ Settings")

    with st.expander("📧 Email Notifications", expanded=True):
        st.markdown(
            """
            Add these to your `.env` file to receive email alerts after each pipeline run:
            ```
            SMTP_HOST=smtp.gmail.com
            SMTP_PORT=587
            SMTP_USER=your@gmail.com
            SMTP_PASS=your-app-password
            NOTIFICATION_EMAIL=your@email.com
            ```
            """
        )
        st.info("ℹ️ For Gmail, use an App Password (not your regular password)")

    with st.expander("🔑 API Keys (Optional)"):
        st.markdown(
            """
            Add these to `.env` for additional job sources:
            ```
            JOOBLE_API_KEY=your-key       # 100 req/day free - https://jooble.org/api/about
            JSEARCH_API_KEY=your-key      # 50/month free - RapidAPI
            ADZUNA_APP_ID=your-id         # 10 req/day free
            ADZUNA_API_KEY=your-key
            ```
            """
        )

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
