"""Reusable Streamlit rendering components: styles, job cards, and results."""

from __future__ import annotations

from typing import Any

import streamlit as st

from jobhunter.domains.search.portals import build_portal_urls
from jobhunter.storage.history import resume_id_from_text

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
def render_results(result: dict[str, Any]) -> None:
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

    source_counts: dict[str, int] = {}
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


def _render_job_card(job: dict[str, Any]) -> None:
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
