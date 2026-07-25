"""Streamlit UI for JobHunter AI — upload a PDF, find Indian jobs, track applications."""

import json
import os
import tempfile
import time
from pathlib import Path

import streamlit as st

from agent import run_job_hunter
from utils import (
    load_applied_jobs,
    save_applied_jobs,
    get_application_history,
    list_all_histories,
    _resume_id,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="JobHunter AI — India Jobs",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Sidebar — Application History
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## 📋 Application History")
    histories = list_all_histories()
    if histories:
        for h in histories:
            rid = h.get("resume_id", "?")
            count = len(h.get("applied_job_ids", []))
            st.markdown(f"- **Resume `{rid}`**: {count} job(s) applied")
    else:
        st.info("No applications yet. Upload a resume to start!")

    st.markdown("---")
    st.markdown("### 🔗 Real Job Portals")
    st.markdown(
        """
        The app opens these portals **directly in your browser**
        with your search query pre-filled. You apply using your
        own logged-in accounts — no API keys needed!
        
        - 🟠 **Naukri** — Indian IT jobs
        - 🔵 **Indeed** — Indian job board
        - 🟣 **LinkedIn** — Professional network
        - 🟤 **Monster** — Indian job portal
        - 🔴 **TimesJobs** — Indian job portal
        - 🟧 **Shine** — Indian job portal
        - 🔍 **Google Jobs** — Aggregates all sources
        """
    )
    st.markdown("---")
    st.markdown(
        "💡 **How it works:**\n\n"
        "1. Upload your resume\n"
        "2. Click 'Run Pipeline'\n"
        "3. Portal links open in your browser tabs\n"
        "4. You're already logged in — just apply!\n\n"
        "✅ Applied jobs are tracked so you never apply twice."
    )
    st.markdown("---")
    st.markdown("---")
    if st.button("🗑️ Clear All History", type="secondary"):
        history_dir = Path("history")
        if history_dir.exists():
            for p in history_dir.glob("*.json"):
                p.unlink()
            st.success("History cleared!")
            st.rerun()


# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown(
    """
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        margin-bottom: 0.25rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #6c757d;
        margin-bottom: 2rem;
    }
    .stat-card {
        background: #f0f2f6;
        border-radius: 12px;
        padding: 1.2rem 1.5rem;
        text-align: center;
    }
    .stat-number {
        font-size: 2rem;
        font-weight: 700;
        color: #0d6efd;
    }
    .stat-label {
        font-size: 0.85rem;
        color: #6c757d;
        margin-top: 0.2rem;
    }
    .job-card {
        background: #ffffff;
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        padding: 1.2rem 1.5rem;
        margin-bottom: 1rem;
    }
    .job-title {
        font-size: 1.15rem;
        font-weight: 600;
    }
    .job-company {
        color: #0d6efd;
        font-weight: 500;
    }
    .job-meta {
        font-size: 0.85rem;
        color: #6c757d;
    }
    .source-badge {
        display: inline-block;
        padding: 0.2rem 0.6rem;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 600;
        color: #fff;
    }
    .source-naukri  { background: #e9692c; }
    .source-indeed  { background: #2164f3; }
    .source-linkedin { background: #0a66c2; }
    .source-adzuna  { background: #6c757d; }
    .app-badge {
        display: inline-block;
        padding: 0.2rem 0.7rem;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 500;
    }
    .applied         { background: #d1e7dd; color: #0f5132; }
    .already_applied { background: #fff3cd; color: #664d03; }
    .error-box {
        background: #f8d7da;
        color: #842029;
        border: 1px solid #f5c2c7;
        border-radius: 8px;
        padding: 1rem;
    }
    .resume-preview {
        background: #f8f9fa;
        border-radius: 8px;
        padding: 1rem;
        font-size: 0.85rem;
        max-height: 300px;
        overflow-y: auto;
        white-space: pre-wrap;
        font-family: monospace;
    }
    .salary-inr {
        font-weight: 500;
        color: #198754;
    }
    footer { display: none; }
</style>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown('<div class="main-header">🤖 JobHunter AI — India</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-header">Upload your resume PDF — AI extracts skills, finds Indian jobs from Naukri, Indeed, LinkedIn, and tracks what you applied to.</div>',
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------
uploaded_file = st.file_uploader(
    "Choose a PDF resume",
    type=["pdf"],
    accept_multiple_files=False,
    help="Upload a PDF file (max 10 MB).",
)

if uploaded_file is not None:
    if uploaded_file.size > 10 * 1024 * 1024:
        st.error("File too large. Maximum size is 10 MB.")
        st.stop()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name

    st.success(f"✅ Uploaded **{uploaded_file.name}** ({uploaded_file.size / 1024:.1f} KB)")

    if st.button("🚀 Run Job Hunter Pipeline", type="primary", use_container_width=True):
        with st.spinner("Running pipeline: extracting resume → generating query → searching jobs → applying..."):
            progress_bar = st.progress(0, text="Starting...")

            try:
                for pct, msg in [
                    (10, "Extracting text from PDF..."),
                    (30, "Generating job search query..."),
                    (55, "Searching Naukri, Indeed, LinkedIn for Indian jobs..."),
                    (80, "Applying to jobs (skipping duplicates)..."),
                    (100, "Done!"),
                ]:
                    time.sleep(0.4)
                    progress_bar.progress(pct, text=msg)

                result = run_job_hunter(tmp_path)
                progress_bar.empty()
            except Exception as exc:
                progress_bar.empty()
                st.error(f"Pipeline failed: {exc}")
                st.stop()
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        # ------------------------------------------------------------------
        # Results
        # ------------------------------------------------------------------
        st.markdown("---")
        st.markdown("## 📊 Results")

        if result.get("error"):
            st.markdown(f'<div class="error-box">⚠️ {result["error"]}</div>', unsafe_allow_html=True)
        else:
            resume_text = result.get("resume_text", "")
            rid = _resume_id(resume_text)

            # Stats row
            jobs = result.get("jobs", [])
            apps = result.get("applications", [])
            applied_count = sum(1 for a in apps if a.get("status") == "applied")
            dup_count = sum(1 for a in apps if a.get("status") == "already_applied")

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.markdown(
                    f"""
                    <div class="stat-card">
                        <div class="stat-number" style="font-size:1rem;">{rid}</div>
                        <div class="stat-label">Resume ID</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with col2:
                st.markdown(
                    f"""
                    <div class="stat-card">
                        <div class="stat-number">{len(jobs)}</div>
                        <div class="stat-label">Jobs Found (Indian)</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with col3:
                st.markdown(
                    f"""
                    <div class="stat-card">
                        <div class="stat-number">{applied_count}</div>
                        <div class="stat-label">New Applications</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with col4:
                st.markdown(
                    f"""
                    <div class="stat-card">
                        <div class="stat-number">{dup_count}</div>
                        <div class="stat-label">Skipped (Already Applied)</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            # Resume preview
            with st.expander("📄 Resume Text Preview", expanded=False):
                st.markdown(f'<div class="resume-preview">{resume_text}</div>', unsafe_allow_html=True)

            # Search query
            st.markdown(f"**🔍 Generated Search Query:** `{result.get('search_query', 'N/A')}`")

            # Source breakdown
            source_counts = {}
            for j in jobs:
                src = j.get("source", "unknown")
                source_counts[src] = source_counts.get(src, 0) + 1
            if source_counts:
                parts = [f"**{src.capitalize()}**: {count}" for src, count in source_counts.items()]
                st.markdown("**📊 Source Breakdown:** " + " | ".join(parts))

            # Jobs list
            st.markdown("### 💼 Indian Jobs Found")
            if not jobs:
                st.info("No jobs found.")
            else:
                for job in jobs:
                    source = job.get("source", "unknown")
                    src_badge = {
                        "naukri": '<span class="source-badge source-naukri">Naukri</span>',
                        "indeed": '<span class="source-badge source-indeed">Indeed</span>',
                        "linkedin": '<span class="source-badge source-linkedin">LinkedIn</span>',
                        "adzuna": '<span class="source-badge source-adzuna">Adzuna</span>',
                    }.get(source, f'<span class="source-badge source-adzuna">{source}</span>')

                    salary = ""
                    if job.get("salary_min") and job.get("salary_max"):
                        sal_min_lakh = job["salary_min"] / 100000
                        sal_max_lakh = job["salary_max"] / 100000
                        salary = f'<span class="salary-inr">₹{sal_min_lakh:.1f}L – ₹{sal_max_lakh:.1f}L</span>'
                    elif job.get("salary_min"):
                        salary = f'<span class="salary-inr">From ₹{job["salary_min"]/100000:.1f}L</span>'
                    elif job.get("salary_max"):
                        salary = f'<span class="salary-inr">Up to ₹{job["salary_max"]/100000:.1f}L</span>'

                    url = job.get("url", "")
                    url_link = f'<a href="{url}" target="_blank">View Job →</a>' if url else ""

                    st.markdown(
                        f"""
                        <div class="job-card">
                            <div style="display:flex; justify-content:space-between; align-items:center;">
                                <div>
                                    <div class="job-title">{job.get("title", "Unknown")}</div>
                                    <div class="job-company">{job.get("company", "Unknown")}</div>
                                    <div class="job-meta">
                                        📍 {job.get("location", "N/A")} &nbsp;|&nbsp; {salary}
                                    </div>
                                </div>
                                <div style="text-align:right;">
                                    {src_badge}
                                    <div style="margin-top:0.3rem; font-size:0.85rem;">{url_link}</div>
                                </div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            # Applications
            st.markdown("### ✅ Application Results")
            if not apps:
                st.info("No applications submitted.")
            else:
                for app in apps:
                    status = app.get("status", "?")
                    badge_class = "applied" if status == "applied" else "already_applied"
                    badge_label = "✅ Applied" if status == "applied" else "⏭️ Already Applied"
                    st.markdown(
                        f"""
                        <div class="job-card">
                            <div style="display:flex; justify-content:space-between; align-items:center;">
                                <div>
                                    <span class="app-badge {badge_class}">{badge_label}</span>
                                    <strong>{app.get("job_title", "Unknown")}</strong>
                                    &nbsp;at&nbsp; <span class="job-company">{app.get("company", "Unknown")}</span>
                                </div>
                                <div class="job-meta" style="font-size:0.8rem;">
                                    {app.get("detail", "")}
                                </div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            # Raw JSON
            with st.expander("📦 Raw JSON Output", expanded=False):
                st.json(result)

    else:
        st.info("👆 Click the button above to start the pipeline.")

else:
    st.info("📄 Upload a PDF resume to get started.")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.caption(
    "JobHunter AI v2.0.0 — Indian job search • Naukri / Indeed / LinkedIn sources • "
    "Duplicate-safe application tracking • Powered by LangGraph & Streamlit"
)