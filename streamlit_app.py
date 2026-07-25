"""JobHunter AI — Streamlit dashboard for resume-based Indian job search with analytics."""

import json
import os
import tempfile
import time
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from agent import run_job_hunter
from utils import (
    load_applied_jobs,
    save_applied_jobs,
    get_application_history,
    list_all_histories,
    list_resumes,
    save_resume,
    delete_resume,
    _resume_id,
    _resume_id_from_file,
    export_history_csv,
    get_analytics_data,
    open_all_portals,
    send_job_alert_email,
    build_portal_urls,
)

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
# Sidebar
# ---------------------------------------------------------------------------
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
        ["🎯 Job Search", "📊 Dashboard", "📝 Resumes", "⚙️ Settings"],
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


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
st.markdown(
    """
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
""",
    unsafe_allow_html=True,
)


# ===========================================================================
# PAGE: JOB SEARCH
# ===========================================================================
if page == "🎯 Job Search":
    st.markdown("## 🎯 Job Search")
    st.markdown("Upload your resume to find matching Indian jobs with AI-powered scoring.")

    # Resume selection / upload
    saved = list_resumes()
    resume_source = st.radio(
        "Resume source",
        ["Upload new PDF", "Use saved resume"],
        horizontal=True,
    )

    resume_text = ""
    file_path = ""

    if resume_source == "Upload new PDF":
        uploaded = st.file_uploader("Choose a PDF resume", type=["pdf"])
        if uploaded:
            if uploaded.size > 10 * 1024 * 1024:
                st.error("Max 10 MB")
                st.stop()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(uploaded.getvalue())
                tmp_path = tmp.name
            file_path = tmp_path
            st.success(f"✅ {uploaded.name} ({uploaded.size/1024:.0f} KB)")

            col1, col2 = st.columns([3, 1])
            with col2:
                name = st.text_input("Save as (optional)")
                if st.button("💾 Save Resume") and name:
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

    # Run pipeline
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
                if resume_source == "Upload new PDF":
                    try:
                        os.unlink(file_path)
                    except Exception:
                        pass

        st.markdown("---")
        st.markdown("## 📊 Results")

        if result.get("error"):
            st.error(f"⚠️ {result['error']}")
        else:
            resume_text = result.get("resume_text", "")
            rid = _resume_id(resume_text)
            jobs = result.get("jobs", [])
            apps = result.get("applications", [])
            query = result.get("search_query", "")

            applied_count = sum(1 for a in apps if a.get("status") == "applied")
            dup_count = sum(1 for a in apps if a.get("status") == "already_applied")

            # Stats
            col1, col2, col3, col4, col5 = st.columns(5)
            with col1:
                st.metric("Jobs Found", len(jobs))
            with col2:
                st.metric("New Applications", applied_count)
            with col3:
                st.metric("Skipped (Duplicate)", dup_count)
            with col4:
                avg_score = sum(j.get("match_score", 0) for j in jobs if j.get("match_score")) / max(len([j for j in jobs if j.get("match_score")]), 1)
                st.metric("Avg Match Score", f"{avg_score:.0f}%")
            with col5:
                st.metric("Resume ID", rid[:8])

            st.markdown(f"**🔍 Query:** `{query}`")

            # Portal quick links
            if query:
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
                            f'</div></a>',
                            unsafe_allow_html=True,
                        )

            # Source breakdown
            source_counts = {}
            for j in jobs:
                src = j.get("source", "unknown")
                source_counts[src] = source_counts.get(src, 0) + 1
            if source_counts:
                parts = [f"**{src.title()}**: {c}" for src, c in sorted(source_counts.items(), key=lambda x: -x[1])]
                st.markdown("**📊 Sources:** " + " | ".join(parts))

            # Jobs with scores
            st.markdown("### 💼 Jobs (Sorted by Match Score)")
            scraped_jobs = [j for j in jobs if not j.get("is_portal_link")]
            portal_jobs = [j for j in jobs if j.get("is_portal_link")]

            if scraped_jobs:
                for job in scraped_jobs:
                    score = job.get("match_score", 0)
                    source = job.get("source", "unknown")
                    score_class = "score-high" if score >= 70 else ("score-mid" if score >= 40 else "score-low")
                    src_tag = f'<span class="source-tag source-{source}">{source.title()}</span>'

                    matched = job.get("matched_skills", [])
                    missing = job.get("missing_skills", [])

                    skills_html = ""
                    if matched:
                        skills_html += "✅ " + " ".join(f'<span class="skill-match">{s}</span>' for s in matched[:5])
                    if missing:
                        if skills_html:
                            skills_html += " &nbsp;|&nbsp; "
                        skills_html += "❌ " + " ".join(f'<span class="skill-missing">{s}</span>' for s in missing[:5])

                    salary = ""
                    if job.get("salary_min") and job.get("salary_max"):
                        salary = f'₹{job["salary_min"]/100000:.1f}L – ₹{job["salary_max"]/100000:.1f}L'

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
            else:
                st.info("No scraped jobs found. Portal links below will open in your browser.")

            # Portal links
            if portal_jobs:
                st.markdown("### 🔗 Portal Search Links")
                cols = st.columns(len(portal_jobs))
                for i, job in enumerate(portal_jobs):
                    with cols[i]:
                        st.markdown(
                            f'<a href="{job["url"]}" target="_blank">'
                            f'<div style="text-align:center; padding:0.5rem; background:#f0f2f6; border-radius:8px;">'
                            f'{job.get("icon", "🔗")} <strong>{job["source"].title()}</strong>'
                            f'</div></a>',
                            unsafe_allow_html=True,
                        )

            # Applications
            st.markdown("### ✅ Application Results")
            if apps:
                for app in apps:
                    status = app.get("status", "?")
                    badge = "✅ Applied" if status == "applied" else "⏭️ Skipped"
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

            # Raw JSON
            with st.expander("📦 Raw Output"):
                st.json(result)


# ===========================================================================
# PAGE: DASHBOARD
# ===========================================================================
elif page == "📊 Dashboard":
    st.markdown("## 📊 Analytics Dashboard")
    data = get_analytics_data()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Applications", data["total_applied"])
    with col2:
        st.metric("Resumes Used", data["total_resumes"])
    with col3:
        st.metric("Unique Jobs", data["unique_jobs"])
    with col4:
        st.metric("Avg/Day", f"{sum(data['daily_counts'].values())/max(len(data['daily_counts']),1):.1f}")

    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("Applications by Source")
        if data["source_counts"]:
            df = pd.DataFrame(
                list(data["source_counts"].items()),
                columns=["Source", "Count"],
            )
            fig = px.pie(df, values="Count", names="Source", hole=0.4)
            fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data yet")

    with col_b:
        st.subheader("Applications Over Time")
        if data["daily_counts"]:
            df = pd.DataFrame(
                list(data["daily_counts"].items()),
                columns=["Date", "Count"],
            )
            fig = px.line(df, x="Date", y="Count", markers=True)
            fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data yet")

    st.subheader("Top Companies")
    if data["top_companies"]:
        df = pd.DataFrame(
            list(data["top_companies"].items()),
            columns=["Company", "Applications"],
        )
        fig = px.bar(df, x="Applications", y="Company", orientation="h")
        fig.update_layout(height=400, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data yet")


# ===========================================================================
# PAGE: RESUMES
# ===========================================================================
elif page == "📝 Resumes":
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
                    f'</span></div>',
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

    # Auto-run if triggered
    if "run_resume_path" in st.session_state and st.session_state["run_resume_path"]:
        fp = st.session_state["run_resume_path"]
        st.session_state["run_resume_path"] = None
        result = run_job_hunter(fp)
        st.json(result)


# ===========================================================================
# PAGE: SETTINGS
# ===========================================================================
elif page == "⚙️ Settings":
    st.markdown("## ⚙️ Settings")

    with st.expander("📧 Email Notifications", expanded=True):
        st.markdown("""
        Add these to your `.env` file to receive email alerts after each pipeline run:
        ```
        SMTP_HOST=smtp.gmail.com
        SMTP_PORT=587
        SMTP_USER=your@gmail.com
        SMTP_PASS=your-app-password
        NOTIFICATION_EMAIL=your@email.com
        ```
        """)
        st.info("ℹ️ For Gmail, use an App Password (not your regular password)")

    with st.expander("🔑 API Keys (Optional)"):
        st.markdown("""
        Add these to `.env` for additional job sources:
        ```
        JOOBLE_API_KEY=your-key       # 100 req/day free - https://jooble.org/api/about
        JSEARCH_API_KEY=your-key      # 50/month free - RapidAPI
        ADZUNA_APP_ID=your-id         # 10 req/day free
        ADZUNA_API_KEY=your-key
        ```
        """)

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

    # Footer
    st.markdown("---")
    st.caption(
        "JobHunter AI v3.0.0 • Indian job search • AI matching • "
        "Playwright scraping • Dashboard analytics • Open source"
    )