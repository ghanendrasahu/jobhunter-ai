"""LangGraph agent that orchestrates resume parsing, job search, and application."""

import logging
from typing import TypedDict, List, Dict, Any

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END

from utils import (
    extract_text_from_pdf,
    search_all_jobs,
    apply_to_job,
    score_jobs,
    send_job_alert_email,
    _resume_id,
)

load_dotenv()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed state – each key is validated at runtime by TypedDict (type‑checked)
# ---------------------------------------------------------------------------
class JobHunterState(TypedDict):
    """Immutable shape of the state dict passed through graph nodes."""

    file_path: str
    resume_text: str
    search_query: str
    jobs: List[Dict[str, Any]]
    applications: List[Dict[str, Any]]
    error: str  # populated if a node fails


# Global LLM instance (cheapest model with strong reasoning)
_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)


# ---------------------------------------------------------------------------
# Graph nodes – each receives & returns a JobHunterState
# ---------------------------------------------------------------------------
def extract_resume(state: JobHunterState) -> JobHunterState:
    """Extract text from the uploaded PDF resume."""
    if state.get("error"):
        return state
    file_path = state.get("file_path", "")
    if not file_path:
        return {**state, "error": "file_path missing in state"}
    try:
        resume_text = extract_text_from_pdf(file_path)
        return {**state, "resume_text": resume_text, "error": ""}
    except Exception as exc:
        logger.exception("PDF extraction failed for %s", file_path)
        return {**state, "error": f"Failed to extract resume: {exc}"}


def generate_query(state: JobHunterState) -> JobHunterState:
    """Use the LLM to produce a concise job search query from the resume.

    Falls back to keyword extraction if the LLM call fails (e.g. quota exceeded).
    """
    if state.get("error"):
        return state
    resume = state.get("resume_text", "")
    if not resume:
        return {**state, "error": "resume_text missing – cannot generate query"}

    # Try LLM first
    try:
        prompt = (
            "Based on the following resume, suggest a single job search query "
            "(job title and key skills) that would return relevant positions. "
            "Return only the query string, no extra text.\n\nResume:\n" + resume
        )
        response = _llm.invoke(prompt)
        query = response.content.strip("\n ")
        if query:
            logger.info("LLM generated query: %s", query)
            return {**state, "search_query": query, "error": ""}
    except Exception as exc:
        logger.warning("LLM query generation failed (%s); falling back to keyword extraction", exc)

    # Fallback: extract keywords directly from resume text
    logger.info("Falling back to keyword extraction from resume")
    lines = resume.splitlines()
    # Take the first non-empty line as a title hint
    title_hint = ""
    for line in lines:
        stripped = line.strip()
        if len(stripped) > 5:
            title_hint = stripped
            break

    # Collect important-sounding words (capitalised phrases, tech keywords)
    import re
    words = re.findall(r"[A-Z][a-z]+(?:\s[A-Z][a-z]+)*", resume)
    # Count frequency
    from collections import Counter
    freq = Counter(words)
    # Filter out common words and short fragments
    common = {"Resume", "Summary", "Experience", "Education", "Skills", "Projects",
              "Certifications", "Languages", "Interests", "Contact", "Phone", "Email",
              "LinkedIn", "GitHub", "Portfolio", "References", "Available", "Upon", "Request"}
    keywords = [w for w in freq if w not in common and len(w) > 2]
    # Pick top 5 by frequency
    top_keywords = [w for w, _ in freq.most_common(15) if w not in common and len(w) > 2][:5]

    if top_keywords:
        query = " ".join(top_keywords)
    elif title_hint:
        query = title_hint
    else:
        query = "Software Engineer"  # ultimate fallback

    logger.info("Fallback extracted query: %s", query)
    return {**state, "search_query": query, "error": ""}


def find_jobs(state: JobHunterState) -> JobHunterState:
    """Search for jobs using the generated query."""
    if state.get("error"):
        return state
    query = state.get("search_query", "")
    if not query:
        return {**state, "error": "search_query missing – cannot search jobs"}
    try:
        jobs = search_all_jobs(query)
        logger.info("Found %d jobs for query: %s", len(jobs), query)
        # Score jobs against resume
        resume_text = state.get("resume_text", "")
        if resume_text and jobs:
            jobs = score_jobs(jobs, resume_text)
        return {**state, "jobs": jobs, "error": ""}
    except Exception as exc:
        logger.exception("Job search failed")
        return {**state, "error": f"Failed to search jobs: {exc}"}


def apply_jobs(state: JobHunterState) -> JobHunterState:
    """Apply to each discovered job."""
    if state.get("error"):
        return state
    resume = state.get("resume_text", "")
    jobs = state.get("jobs", [])
    if not jobs:
        logger.warning("No jobs to apply to")
        return {**state, "applications": [], "error": ""}

    applications: List[Dict[str, Any]] = []
    errors: List[str] = []
    for job in jobs:
        try:
            result = apply_to_job(job, resume)
            applications.append(result)
        except Exception as exc:
            logger.exception("Failed to apply to job %s", job.get("id"))
            errors.append(str(exc))

    if errors:
        logger.warning("%d application(s) failed", len(errors))
    logger.info("Applied to %d / %d jobs", len(applications), len(jobs))

    # Send email notification if configured
    query = state.get("search_query", "")
    if applications and query:
        send_job_alert_email(query, len(jobs), len(applications))

    return {**state, "applications": applications, "error": ""}


# ---------------------------------------------------------------------------
# Build the executable graph
# ---------------------------------------------------------------------------
workflow = StateGraph(JobHunterState)
workflow.add_edge(START, "extract_resume")
workflow.add_node("extract_resume", extract_resume)
workflow.add_node("generate_query", generate_query)
workflow.add_node("find_jobs", find_jobs)
workflow.add_node("apply_jobs", apply_jobs)
workflow.add_edge("extract_resume", "generate_query")
workflow.add_edge("generate_query", "find_jobs")
workflow.add_edge("find_jobs", "apply_jobs")
workflow.add_edge("apply_jobs", END)

job_hunter_app = workflow.compile()


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------
def run_job_hunter(file_path: str) -> Dict[str, Any]:
    """Execute the full pipeline given a resume PDF path.

    Returns the final state dict (suitable for JSON serialisation).
    """
    logger.info("Starting JobHunter pipeline for %s", file_path)
    initial_state: JobHunterState = {
        "file_path": file_path,
        "resume_text": "",
        "search_query": "",
        "jobs": [],
        "applications": [],
        "error": "",
    }
    final_state = job_hunter_app.invoke(initial_state)
    logger.info("JobHunter pipeline complete")
    return dict(final_state)
