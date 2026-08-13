"""JobHunter AI — Streamlit dashboard for resume-based Indian job search with analytics."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import plotly.express as px
import streamlit as st

from jobhunter.agent import run_job_hunter
from jobhunter.automation import run_application_pipeline
from jobhunter.config import get_settings
from jobhunter.core.analytics import get_analytics_data
from jobhunter.core.history import (
    delete_resume,
    export_history_csv,
    list_all_histories,
    list_resumes,
    resume_id_from_text,
    save_resume,
)
from jobhunter.core.pdf import extract_text_from_pdf
from jobhunter.search.portals import build_portal_urls

MAX_UPLOAD_MB = 10

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="JobHunter AI",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
_CSS = """
<style>
.job-card {
    background: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 10px;
    padding: 1rem 1.2rem;
    margin-bottom: 0.8rem;
}
.score-badge {
    display: inline-block;
    padding: 0.2rem 0.6rem;
    border-radius: 20px;
    font-size: 0.8rem;
    font-weight: 700;
}
.score-high { background: #d1e7dd; color: #0f5132; }
.score-mid  { background: #fff3cd; color: #664d03; }
.score-low  { background: #f8d7da; color: #842029; }
.source-tag {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 10px;
    font-size: 0.7rem;
    font-weight: 600;
    color: #fff;
}
.source-naukri  { background: #e9692c; }
.source-indeed  { background: #2164f3; }
.source-linkedin { background: #0a66c2; }
.source-monster { background: #6c2bd9; }
.source-adzuna  { background: #6c757d; }
.source-jooble  { background: #198754; }
.skill-match { color: #198754; font-weight: 500; }
.skill-missing { color: #dc3545; }
.resume-card {
    background: #f8f9fa;
    border-radius: 8px;
    padding: 0.8rem 1rem;
    margin-bottom: 0.5rem;
}
</style>
"""


# ---------------------------------------------------------------------------
# Results rendering (shared between Job Search and Resumes pages)
# ---------------------------------------------------------------------------
def render_results(result: Dict[str, Any]) -> None:
    """Render pipeline results: stats, portal links, scored jobs, applications."""
    if result.get("error"):
        st.error(f"⚠️ {result['error']}")
        return

    resume_text = result.get("resume_text", "")
    rid = resume_id_from_text(resume_text) if resume_text else "n/a"
    jobs = result.get("jobs", [])
    apps = result.get("applications", [])
    query = result.get("search_query", "")

    applied_count = sum(1 for a in apps if a.get("status") == "applied")
    dup_count = sum(1 for a in apps if a.get("status") == "already_applied")

    scored = [j for j in jobs if j.get("match_score") is not None]
    avg_score = sum(j["match_score"] for j in scored) / len(scored) if scored else 0

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Jobs Found", len(jobs))
    col2.metric("New Applications", applied_count)
    col3.metric("Skipped (Duplicate)", dup_count)
    col4.metric("Avg Match Score", f"{avg_score:.0f}%")
    col5.metric("Resume ID", rid[:8])

    if query:
        st.markdown(f"**🔍 Query:** `{query}`")

        st.markdown("### 🔗 Quick Open Portals")
        portal_links = build_portal_urls(query)
        cols = st.columns(len(portal_links))
        for i, portal in enumerate(portal_links):
            with cols[i]:
                st.markdown(
                    f'<a href="{portal["url"]}" target="_blank" style="text-decoration:none;">'
                    f'<div style="text-align:center; padding:0.5rem; background:#f8f9fa; border-radius:8px;">'
                    f'<div style="font-size:1.5rem;">{portal.get("icon", "🔗")}</div>'
                    f'<div style="font-size:0.75rem; font-weight:600;">{portal["source"].title()}</div>'
                    f"</div></a>",
                    unsafe_allow_html=True,
                )

    source_counts: Dict[str, int] = {}
    for j in jobs:
        src = j.get("source", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1
    if source_counts:
        parts = [f"**{src.title()}**: {count}" for src, count in sorted(source_counts.items(), key=lambda x: -x[1])]
        st.markdown("**📊 Sources:** " + " | ".join(parts))

    st.markdown("### 💼 Jobs (Sorted by Match Score)")
    scraped_jobs = [j for j in jobs if not j.get("is_portal_link")]
    portal_jobs = [j for j in jobs if j.get("is_portal_link")]

    if scraped_jobs:
        for job in scraped_jobs:
            _render_job_card(job)
    else:
        st.info("No scraped jobs found. Portal links below will open in your browser.")

    if portal_jobs:
        st.markdown("### 🔗 Portal Search Links")
        cols = st.columns(len(portal_jobs))
        for i, job in enumerate(portal_jobs):
            with cols[i]:
                st.markdown(
                    f'<a href="{job["url"]}" target="_blank">'
                    f'<div style="text-align:center; padding:0.5rem; background:#f0f2f6; border-radius:8px;">'
                    f'{job.get("icon", "🔗")} <strong>{job["source"].title()}</strong>'
                    f"</div></a>",
                    unsafe_allow_html=True,
                )

    st.markdown("### ✅ Application Results")
    if apps:
        for app in apps:
            status = app.get("status", "?")
            badge = {
                "applied": "✅ Applied",
                "already_applied": "⏭️ Skipped",
                "failed": "❌ Failed",
            }.get(status, status)
            score = app.get("match_score")
            score_str = f" | Match: {score}%" if score else ""
            st.markdown(
                f"""
                <div class="job-card" style="padding:0.6rem 1rem;">
                    <span style="font-weight:500;">{badge}</span>
                    <strong>{app.get("job_title", "?")}</strong> @ {app.get("company", "?")}
                    <span style="font-size:0.8rem; color:#6c757d;">{score_str}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.info("No applications recorded.")

    with st.expander("📦 Raw Output"):
        st.json(result)


def _render_job_card(job: Dict[str, Any]) -> None:
    """Render a single scored job card."""
    score = job.get("match_score", 0)
    source = job.get("source", "unknown")
    score_class = "score-high" if score >= 70 else ("score-mid" if score >= 40 else "score-low")
    src_tag = f'<span class="source-tag source-{source}">{source.title()}</span>'

    skills_html = ""
    matched = job.get("matched_skills", [])
    missing = job.get("missing_skills", [])
    if matched:
        skills_html += "✅ " + " ".join(f'<span class="skill-match">{s}</span>' for s in matched[:5])
    if missing:
        if skills_html:
            skills_html += " &nbsp;|&nbsp; "
        skills_html += "❌ " + " ".join(f'<span class="skill-missing">{s}</span>' for s in missing[:5])

    salary = ""
    if job.get("salary_min") and job.get("salary_max"):
        salary = f'₹{job["salary_min"] / 100000:.1f}L – ₹{job["salary_max"] / 100000:.1f}L'

    url = job.get("url", "")
    url_link = f'<a href="{url}" target="_blank">🔗 Apply</a>' if url else ""

    st.markdown(
        f"""
        <div class="job-card">
            <div style="display:flex; justify-content:space-between; align-items:start;">
                <div style="flex:1;">
                    <strong>{job.get("title", "Unknown")}</strong>
                    <span class="score-badge {score_class}">{score}%</span>
                    {src_tag}
                    <div style="font-size:0.85rem; color:#0d6efd;">{job.get("company", "")}</div>
                    <div style="font-size:0.8rem; color:#6c757d;">
                        📍 {job.get("location", "India")}
                        {' | ' + salary if salary else ''}
                    </div>
                    <div style="font-size:0.8rem; margin-top:0.3rem;">{skills_html}</div>
                </div>
                <div style="text-align:right; font-size:0.85rem;">{url_link}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def render_sidebar() -> str:
    """Render the sidebar and return the selected page name."""
    with st.sidebar:
        st.markdown("## 🤖 JobHunter AI")
        st.markdown("### 📋 Application History")

        histories = list_all_histories()
        total_applied = sum(len(h.get("applied_job_ids", [])) for h in histories)
        st.metric("Total Applications", total_applied)

        if histories:
            for h in histories:
                rid = h.get("resume_id", "?")
                count = len(h.get("applied_job_ids", []))
                st.markdown(f"- `{rid}`: {count} job(s)")
        else:
            st.info("No applications yet.")

        st.markdown("---")
        page = st.radio(
            "Navigate",
            ["🎯 Job Search", "🤖 Auto Apply", "📊 Dashboard", "📝 Resumes", "⚙️ Settings"],
            label_visibility="collapsed",
        )

        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🗑️ Clear History", use_container_width=True):
                for p in Path("history").glob("*.json"):
                    p.unlink()
                st.rerun()
        with col2:
            if histories:
                csv_data = export_history_csv()
                st.download_button(
                    "📥 Export CSV",
                    data=csv_data,
                    file_name="jobhunter_history.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
    return page


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
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
            st.caption("Portals need credentials in `.env` (NAUKRI_EMAIL/NAUKRI_PASSWORD, INDEED_EMAIL/INDEED_PASSWORD).")

    with col_right:
        st.markdown("#### Portal credentials")
        st.code(
            "NAUKRI_EMAIL=you@email.com\nNAUKRI_PASSWORD=...\nINDEED_EMAIL=you@email.com\nINDEED_PASSWORD=..."
        )
        st.markdown("#### What happens")
        st.markdown("1. Opens a persistent browser (logged-in session reused)")
        st.markdown("2. Searches each portal for your query")
        st.markdown("3. Groq scores every job → apply/skip decision")
        st.markdown("4. Opens apply form & pre-fills from your resume")
        st.markdown("5. Records applications to your history")

    if resume_text and st.button("🚀 Run Apply Agent", type="primary", use_container_width=True):
        with st.status("Running apply agent…", expanded=True) as status:
            status_log: Dict[str, str] = {}

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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    page = render_sidebar()

    if page == "🎯 Job Search":
        job_search_page()
    elif page == "🤖 Auto Apply":
        auto_apply_page()
    elif page == "📊 Dashboard":
        dashboard_page()
    elif page == "📝 Resumes":
        resumes_page()
    else:
        settings_page()

    st.markdown("---")
    st.caption(
        "JobHunter AI v3.0.0 • Indian job search • AI matching • "
        "Playwright scraping • Dashboard analytics • Open source"
    )


if __name__ == "__main__":
    main()
