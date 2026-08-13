"""LangGraph agent orchestrating resume parsing, job search, scoring, and application."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, TypedDict

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from jobhunter.config import get_settings
from jobhunter.core.history import apply_to_job
from jobhunter.core.matcher import score_jobs
from jobhunter.core.pdf import extract_text_from_pdf
from jobhunter.notifications import send_job_alert_email
from jobhunter.search.engine import search_all_jobs

load_dotenv()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed state flowing through the graph
# ---------------------------------------------------------------------------
class JobHunterState(TypedDict):
    """Shape of the state dict passed between graph nodes."""

    file_path: str
    resume_text: str
    search_query: str
    jobs: List[Dict[str, Any]]
    applications: List[Dict[str, Any]]
    error: str


def _default_llm() -> ChatOpenAI:
    """Create the default chat model from settings (lazy, so tests can inject fakes)."""
    settings = get_settings()
    return ChatOpenAI(model=settings.openai_model, temperature=0.0)


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------
def extract_resume(state: JobHunterState) -> JobHunterState:
    """Extract text from the PDF resume."""
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


def _make_generate_query(llm: ChatOpenAI):
    """Build the query-generation node bound to a specific LLM."""

    def generate_query(state: JobHunterState) -> JobHunterState:
        if state.get("error"):
            return state
        resume = state.get("resume_text", "")
        if not resume:
            return {**state, "error": "resume_text missing – cannot generate query"}

        try:
            prompt = (
                "Based on the following resume, suggest a single job search query "
                "(job title and key skills) that would return relevant positions. "
                "Return only the query string, no extra text.\n\nResume:\n" + resume
            )
            response = llm.invoke(prompt)
            query = (response.content or "").strip()
            if query:
                logger.info("LLM generated query: %s", query)
                return {**state, "search_query": query, "error": ""}
        except Exception as exc:
            logger.warning("LLM query generation failed (%s); using keyword fallback", exc)

        return {**state, "search_query": _keyword_query(resume), "error": ""}

    return generate_query


def _keyword_query(resume: str) -> str:
    """Fallback query built from frequent capitalised phrases in the resume."""
    import re
    from collections import Counter

    common = {
        "Resume", "Summary", "Experience", "Education", "Skills", "Projects",
        "Certifications", "Languages", "Interests", "Contact", "Phone", "Email",
        "LinkedIn", "GitHub", "Portfolio", "References", "Available", "Upon", "Request",
    }
    words = re.findall(r"[A-Z][a-z]+(?:\s[A-Z][a-z]+)*", resume)
    freq = Counter(words)
    top = [w for w, _ in freq.most_common(15) if w not in common and len(w) > 2][:5]

    if top:
        return " ".join(top)

    for line in resume.splitlines():
        stripped = line.strip()
        if len(stripped) > 5:
            return stripped
    return "Software Engineer"


def find_jobs(state: JobHunterState) -> JobHunterState:
    """Search for jobs using the generated query and score them against the resume."""
    if state.get("error"):
        return state
    query = state.get("search_query", "")
    if not query:
        return {**state, "error": "search_query missing – cannot search jobs"}
    try:
        jobs = search_all_jobs(query)
        logger.info("Found %d jobs for query: %s", len(jobs), query)
        if jobs and state.get("resume_text"):
            jobs = score_jobs(jobs, state["resume_text"])
        return {**state, "jobs": jobs, "error": ""}
    except Exception as exc:
        logger.exception("Job search failed")
        return {**state, "error": f"Failed to search jobs: {exc}"}


def apply_jobs(state: JobHunterState) -> JobHunterState:
    """Record applications for each discovered job."""
    if state.get("error"):
        return state
    resume = state.get("resume_text", "")
    jobs = state.get("jobs", [])
    if not jobs:
        logger.warning("No jobs to apply to")
        return {**state, "applications": [], "error": ""}

    applications: List[Dict[str, Any]] = []
    for job in jobs:
        try:
            applications.append(apply_to_job(job, resume))
        except Exception as exc:
            logger.exception("Failed to apply to job %s", job.get("id"))
            applications.append({
                "job_id": job.get("id"),
                "job_title": job.get("title"),
                "company": job.get("company"),
                "status": "failed",
                "detail": str(exc),
            })

    logger.info("Applied to %d / %d jobs", len(applications), len(jobs))

    query = state.get("search_query", "")
    if applications and query:
        send_job_alert_email(query, len(jobs), len(applications))

    return {**state, "applications": applications, "error": ""}


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------
def create_agent(llm: ChatOpenAI = None):
    """Build a compiled LangGraph pipeline.

    ``llm`` is injectable for tests; it defaults to the configured chat model.
    """
    llm = llm or _default_llm()

    workflow = StateGraph(JobHunterState)
    workflow.add_node("extract_resume", extract_resume)
    workflow.add_node("generate_query", _make_generate_query(llm))
    workflow.add_node("find_jobs", find_jobs)
    workflow.add_node("apply_jobs", apply_jobs)

    workflow.add_edge(START, "extract_resume")
    workflow.add_edge("extract_resume", "generate_query")
    workflow.add_edge("generate_query", "find_jobs")
    workflow.add_edge("find_jobs", "apply_jobs")
    workflow.add_edge("apply_jobs", END)

    return workflow.compile()


job_hunter_app = create_agent()


def run_job_hunter(file_path: str, agent: Any = None) -> Dict[str, Any]:
    """Execute the full pipeline for a resume PDF and return the final state.

    ``agent`` is optional for testing; defaults to the module-level compiled graph.
    """
    logger.info("Starting JobHunter pipeline for %s", file_path)
    compiled = agent or job_hunter_app
    initial_state: JobHunterState = {
        "file_path": file_path,
        "resume_text": "",
        "search_query": "",
        "jobs": [],
        "applications": [],
        "error": "",
    }
    final_state = compiled.invoke(initial_state)
    logger.info("JobHunter pipeline complete")
    return dict(final_state)
