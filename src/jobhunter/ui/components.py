"""Reusable Streamlit rendering components: styles, job cards, and results."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from jobhunter.domains.search.portals import build_portal_urls
from jobhunter.storage.history import resume_id_from_text
from jobhunter.ui import design as ui

# ---------------------------------------------------------------------------
# App-specific styles (layered on top of the shared design system)
# ---------------------------------------------------------------------------
_CSS = """
<style>
.jh-side-label {
    font-size: 11px; font-weight: 600; letter-spacing: .12em; text-transform: uppercase;
    color: var(--ui-muted); margin: 1.1rem 0 .45rem;
}
.jh-hist-list { display: flex; flex-direction: column; gap: .25rem; }
.jh-hist {
    display: flex; justify-content: space-between; align-items: center;
    padding: .4rem .5rem; border-radius: 8px; background: var(--ui-surface);
    font-size: 12px; color: var(--ui-muted);
}
.jh-hist-date { color: var(--ui-muted); }
.jh-hist-count { color: var(--ui-text); font-weight: 600; }

.jh-job {
    background: var(--ui-surface); border: 1px solid var(--ui-border);
    border-radius: var(--ui-radius); padding: 1rem 1.1rem; margin-bottom: .65rem;
}
.jh-job-top { display: flex; justify-content: space-between; gap: 1rem; align-items: flex-start; }
.jh-job-title { font-size: 15px; font-weight: 650; color: var(--ui-text); }
.jh-job-company { font-size: 13px; color: var(--ui-primary); margin-top: .1rem; }
.jh-job-meta { font-size: 13px; color: var(--ui-muted); margin-top: .3rem; }
.jh-job-skills { font-size: 12px; margin-top: .45rem; display: flex; flex-wrap: wrap; gap: .35rem; }
.jh-skill { padding: .1rem .45rem; border-radius: 6px; }
.jh-skill.matched { color: #8BE8C3; background: rgba(70,211,154,.10); }
.jh-skill.missing { color: #F5A3A3; background: rgba(241,124,124,.10); }
.jh-apply { font-size: 13px; font-weight: 600; white-space: nowrap; }

.jh-score {
    display: inline-block; padding: .12rem .5rem; border-radius: 999px;
    font-size: 12px; font-weight: 700; margin-left: .5rem;
}
.jh-score.high { background: rgba(70,211,154,.12); color: #8BE8C3; }
.jh-score.mid { background: rgba(242,181,68,.12); color: #F7CD7A; }
.jh-score.low { background: rgba(241,124,124,.12); color: #F5A3A3; }

.jh-source {
    display: inline-block; padding: .08rem .45rem; border-radius: 6px;
    font-size: 11px; font-weight: 600; letter-spacing: .02em;
    color: var(--ui-muted); background: var(--ui-surface-2); border: 1px solid var(--ui-border);
}
.jh-portals { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: .6rem; }
.jh-portal {
    display: flex; align-items: center; justify-content: space-between; gap: .5rem;
    padding: .7rem .8rem; border-radius: var(--ui-radius-sm);
    background: var(--ui-surface); border: 1px solid var(--ui-border);
    color: var(--ui-text) !important; font-size: 13px; font-weight: 600; text-decoration: none !important;
}
.jh-portal:hover { border-color: var(--ui-border-strong); background: var(--ui-surface-2); }
.jh-portal svg { color: var(--ui-muted); }
.jh-app-row {
    display: flex; align-items: center; justify-content: space-between; gap: .75rem;
    padding: .65rem .8rem; border-radius: var(--ui-radius-sm);
    background: var(--ui-surface); border: 1px solid var(--ui-border); margin-bottom: .4rem;
}
.jh-resume {
    background: var(--ui-surface); border: 1px solid var(--ui-border);
    border-radius: var(--ui-radius-sm); padding: .7rem .85rem;
}
.jh-resume-name { font-size: 14px; font-weight: 600; color: var(--ui-text); }

.jh-features {
    display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: .75rem; margin-top: .9rem;
}
.jh-feature {
    background: var(--ui-surface); border: 1px solid var(--ui-border);
    border-radius: var(--ui-radius); padding: 1rem 1.1rem;
}
.jh-feature svg { color: var(--ui-primary); }
.jh-feature-title { margin-top: .55rem; font-size: 14px; font-weight: 600; color: var(--ui-text); }
.jh-feature-body { margin-top: .25rem; font-size: 13px; line-height: 1.55; color: var(--ui-muted); }
@media (max-width: 640px) {
    .jh-features { grid-template-columns: 1fr; }
}
.jh-status { font-size: 12px; font-weight: 700; padding: .1rem .5rem; border-radius: 999px; }
.jh-status.applied { color: #8BE8C3; background: rgba(70,211,154,.12); }
.jh-status.skipped { color: #F7CD7A; background: rgba(242,181,68,.12); }
.jh-status.failed { color: #F5A3A3; background: rgba(241,124,124,.12); }
</style>
"""


# ---------------------------------------------------------------------------
# Results rendering (shared between Job Search and Resumes pages)
# ---------------------------------------------------------------------------
def render_results(result: dict[str, Any]) -> None:
    """Render pipeline results: stats, portal links, scored jobs, applications."""
    if result.get("error"):
        ui.error_state(
            str(result["error"]),
            title="The pipeline could not finish",
            hint="Check the log above, then run it again.",
        )
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

    ui.metric_grid(
        [
            {"label": "Jobs found", "value": f"{len(jobs):,}", "caption": "across every source"},
            {"label": "New applications", "value": f"{applied_count:,}", "caption": "submitted this run"},
            {"label": "Duplicates skipped", "value": f"{dup_count:,}", "caption": "already in your history"},
            {"label": "Average match", "value": f"{avg_score:.0f}%", "caption": "across scored jobs"},
            {"label": "Resume", "value": rid[:8], "caption": "run identifier"},
        ]
    )

    if query:
        ui.section("Quick search", f"Open the same query on each portal for “{escape(query)}”.")
        _render_portal_grid(build_portal_urls(query))

    ui.section(
        "Matched jobs", "Sorted by match score. Missing skills are shown so you can tailor your resume."
    )
    scraped_jobs = [j for j in jobs if not j.get("is_portal_link")]
    if scraped_jobs:
        for rank, job in enumerate(scraped_jobs, start=1):
            _render_job_card(job, rank=rank)
    else:
        ui.empty_state(
            "No scraped jobs this run",
            "The portals below still work as manual searches. Try a broader query or another portal.",
            icon_name="search",
        )

    ui.section("Applications", "What the agent submitted, skipped, or could not complete — with the reason.")
    if apps:
        for app in apps:
            status = app.get("status", "?")
            status_class = {
                "submitted": "applied",
                "applied": "applied",
                "already_applied": "skipped",
                "needs_review": "skipped",
                "failed": "failed",
                "blocked": "failed",
                "no_apply_button": "failed",
            }.get(status, "")
            label = {
                "submitted": "Submitted",
                "applied": "Applied",
                "already_applied": "Skipped",
                "needs_review": "Needs review",
                "failed": "Failed",
                "blocked": "Blocked",
                "no_apply_button": "No apply button",
            }.get(status, status)
            detail = app.get("detail") or ""
            score = app.get("match_score")
            score_html = f" · {score}% match" if score else ""
            st.markdown(
                f'<div class="jh-app-row">'
                f'<div><span class="jh-status {status_class}">{escape(label)}</span> '
                f"<strong>{escape(str(app.get('job_title', 'Untitled role')))}</strong>"
                f'<span class="jh-job-meta"> @ {escape(str(app.get("company", "Unknown")))}'
                f"{score_html}</span><br/>"
                f'<span class="jh-job-meta">{escape(str(detail))}</span></div></div>',
                unsafe_allow_html=True,
            )
    else:
        ui.empty_state(
            "No applications recorded",
            "Nothing was submitted in this run. If you expected applications, check the log above.",
            icon_name="briefcase",
        )


def _render_portal_grid(portals: list[dict[str, Any]]) -> None:
    tiles = "".join(
        f'<a class="jh-portal" href="{escape(str(p["url"]))}" target="_blank" rel="noopener">'
        f"<span>{escape(str(p.get('source', '')).title())}</span>{ui.svg('arrow-right', 16)}</a>"
        for p in portals
    )
    st.markdown(f'<div class="jh-portals">{tiles}</div>', unsafe_allow_html=True)


def _render_job_card(job: dict[str, Any], rank: int | None = None) -> None:
    """Render a single scored job card."""
    score = int(job.get("match_score") or 0)
    source = str(job.get("source", "unknown")).title()
    score_class = "high" if score >= 70 else ("mid" if score >= 40 else "low")
    rank_html = f"<span class='jh-source'>#{rank}</span> " if rank else ""
    eligibility = str(job.get("eligibility_decision") or "unreviewed")
    discovery_only = bool(job.get("discovery_only"))

    skills_html = ""
    matched = job.get("matched_skills", []) or []
    missing = job.get("missing_skills", []) or []
    if matched:
        skills_html += "".join(
            f'<span class="jh-skill matched">+ {escape(str(s))}</span>' for s in matched[:6]
        )
    if missing:
        skills_html += "".join(
            f'<span class="jh-skill missing">− {escape(str(s))}</span>' for s in missing[:6]
        )
    skills_block = f'<div class="jh-job-skills">{skills_html}</div>' if skills_html else ""

    salary = ""
    if job.get("salary_min") and job.get("salary_max"):
        salary = f" · ₹{job['salary_min'] / 100000:.1f}L – ₹{job['salary_max'] / 100000:.1f}L"

    url = job.get("url", "")
    apply_html = (
        f'<a class="jh-apply" href="{escape(str(url))}" target="_blank" rel="noopener">'
        f"Apply {ui.svg('arrow-right', 13)}</a>"
        if url
        else ""
    )
    discovery_badge = ' · <span class="jh-source">discovery only</span>' if discovery_only else ""

    st.markdown(
        f'<div class="jh-job">'
        f'<div class="jh-job-top"><div>'
        f'<div class="jh-job-title">{rank_html}{escape(str(job.get("title", "Untitled role")))}'
        f'<span class="jh-score {score_class}">{score}%</span></div>'
        f'<div class="jh-job-company">{escape(str(job.get("company", "")))}</div>'
        f'<div class="jh-job-meta">{escape(str(job.get("location", "India")))}'
        f'{escape(salary)} · <span class="jh-source">{escape(source)}</span>'
        f' · <span class="jh-source">{escape(eligibility)}</span>'
        f"{discovery_badge}</div>"
        f"{skills_block}</div><div>{apply_html}</div></div></div>",
        unsafe_allow_html=True,
    )
    _render_job_explanation(job)


def _render_job_explanation(job: dict[str, Any]) -> None:
    """Expandable audit trail: eligibility -> relevance -> application decision."""
    with st.expander("Why this score & eligibility"):
        eligibility_decision = job.get("eligibility_decision") or "unreviewed"
        eligibility_status = job.get("eligibility_status") or "unknown"
        st.markdown(
            f"**Eligibility:** {escape(str(eligibility_status))} → `{escape(str(eligibility_decision))}`"
        )
        reasons = job.get("eligibility_reasons") or []
        if reasons:
            for reason in reasons:
                st.markdown(f"- {escape(str(reason))}")
        exposed = job.get("eligibility_exposed") or []
        if exposed:
            st.caption("Cannot be safely resolved (never guessed):")
            for item in exposed:
                st.markdown(f"- {escape(str(item))}")
        relevance_decision = job.get("relevance_decision") or "unscored"
        relevance_score = job.get("match_score")
        explanation = job.get("relevance_explanation") or ""
        st.markdown(
            f"**Relevance:** `{escape(str(relevance_decision))}`"
            + (f" · score {escape(str(relevance_score))}" if relevance_score is not None else "")
        )
        if explanation:
            st.caption(str(explanation))
        components = job.get("relevance_components") or []
        if components:
            for comp in components:
                name = escape(str(comp.get("name", "?")))
                weight = comp.get("weight")
                cscore = comp.get("score")
                detail = escape(str(comp.get("detail", "")))
                st.markdown(f"- **{name}** (weight {weight}): {cscore} — {detail}")
        if job.get("semantic_reason"):
            st.markdown(
                f"- **Semantic match:** {escape(str(job.get('semantic_score', '')))} — {escape(str(job.get('semantic_reason')))}"
            )
