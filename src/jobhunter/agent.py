"""LangGraph agent orchestrating resume parsing, job search, scoring, and application."""

from __future__ import annotations

import logging
from typing import Any, TypedDict, cast

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import SecretStr

from jobhunter.config import get_settings
from jobhunter.domains.candidate import Candidate
from jobhunter.domains.eligibility import evaluate_eligibility
from jobhunter.domains.resume import extract_text_from_pdf
from jobhunter.domains.scoring import score_relevance
from jobhunter.domains.search.engine import search_plan_jobs
from jobhunter.domains.search.plan import build_search_plan
from jobhunter.services.notifications import send_job_alert_email
from jobhunter.storage.history import apply_to_job

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
    candidate: Candidate | None
    jobs: list[dict[str, Any]]
    applications: list[dict[str, Any]]
    error: str


def _default_llm() -> ChatOpenAI:
    """Create the default chat model from settings (lazy, so tests can inject fakes).

    Prefers Groq when ``GROQ_API_KEY`` is configured; otherwise uses OpenAI.
    """
    settings = get_settings()
    if settings.groq_api_key:
        return ChatOpenAI(
            model=settings.groq_model,
            api_key=cast(SecretStr, settings.groq_api_key),
            base_url=settings.groq_base_url,
            temperature=0.0,
        )
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
            content = response.content
            query = content.strip() if isinstance(content, str) else ""
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


def _make_find_jobs(llm: ChatOpenAI):
    """Build the job-search node (search only; scoring happens after eligibility).

    A search plan is derived from the query plus candidate knowledge (role
    family, skills) so searches keep widening coverage without repeating
    equivalent terms.
    """

    def find_jobs(state: JobHunterState) -> JobHunterState:
        if state.get("error"):
            return state
        query = state.get("search_query", "")
        if not query:
            return {**state, "error": "search_query missing – cannot search jobs"}
        try:
            plan = build_search_plan(query, candidate=state.get("candidate"), settings=get_settings())
            jobs = search_plan_jobs(plan)
            logger.info("Found %d jobs for query: %s", len(jobs), query)
            return {**state, "jobs": jobs, "error": ""}
        except Exception as exc:
            logger.exception("Job search failed")
            return {**state, "error": f"Failed to search jobs: {exc}"}

    return find_jobs


def build_candidate_knowledge(state: JobHunterState) -> JobHunterState:
    """Build the CandidateKnowledge model from the resume (before eligibility)."""
    if state.get("error"):
        return state
    resume = state.get("resume_text", "")
    if not resume:
        return {**state, "error": "resume_text missing – cannot build candidate knowledge"}
    try:
        from jobhunter.automation.candidate import build_candidate  # local import to avoid cycles

        candidate = build_candidate(resume, profile=None)
        logger.info(
            "Candidate knowledge: %s, experience=%s, seniority=%s",
            candidate.role_family or "unknown",
            candidate.experience_years if candidate.experience_years is not None else "unknown",
            candidate.seniority or "unknown",
        )
        return {**state, "candidate": candidate, "error": ""}
    except Exception as exc:
        logger.exception("Candidate knowledge build failed")
        return {**state, "error": f"Failed to build candidate knowledge: {exc}"}


def assess_eligibility(state: JobHunterState) -> JobHunterState:
    """Run the HARD eligibility gate for every job before any scoring."""
    if state.get("error"):
        return state
    candidate = state.get("candidate")
    jobs = state.get("jobs", [])
    for job in jobs:
        try:
            result = evaluate_eligibility(job, candidate=candidate)
            job["eligibility_status"] = result.status
            job["eligibility_decision"] = result.decision
            job["eligibility_reasons"] = result.reasons
            job["eligibility_exposed"] = result.exposed
            job["eligibility_requirements"] = [r.to_dict() for r in result.requirements]
        except Exception as exc:
            logger.exception("Eligibility gate failed for job %s", job.get("id"))
            job["eligibility_status"] = "waiting_for_user"
            job["eligibility_decision"] = "review"
            job["eligibility_reasons"] = [f"Eligibility gate errored: {exc}"]
            job["eligibility_exposed"] = []
            job["eligibility_requirements"] = []
    return state


def _make_score_jobs(llm: ChatOpenAI):
    """Build the relevance-scoring node; only eligibility-cleared jobs are scored.

    The deterministic subscore computation is cheap, but each eligible job may
    trigger an LLM refinement call. Those calls are run concurrently (bounded by
    ``score_max_workers``) so a batch of jobs finishes in roughly one LLM
    round-trip instead of ``len(eligible)`` of them.
    """

    def score(state: JobHunterState) -> JobHunterState:
        if state.get("error"):
            return state
        resume = state.get("resume_text", "")
        candidate = state.get("candidate")
        jobs = state.get("jobs", [])
        eligible: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for job in jobs:
            if job.get("eligibility_decision") == "apply":
                eligible.append(job)
            else:
                skipped.append(job)

        if eligible:
            from concurrent.futures import ThreadPoolExecutor

            def _score_one(job: dict[str, Any]):
                return score_relevance(job, candidate=candidate, resume_text=resume, llm=llm)

            workers = min(len(eligible), max(1, get_settings().score_max_workers))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                scored = pool.map(_score_one, eligible)
                for job, result in zip(eligible, scored, strict=True):
                    job["match_score"] = result.overall
                    job["relevance_score"] = result.overall
                    job["relevance_decision"] = result.decision
                    job["relevance_components"] = [c.to_dict() for c in result.components]
                    job["relevance_explanation"] = result.explanation
                    if result.semantic_score is not None:
                        job["semantic_score"] = result.semantic_score
                        job["semantic_reason"] = result.semantic_reason

        eligible.sort(key=lambda j: j.get("match_score", 0), reverse=True)
        logger.info(
            "Scored %d/%d jobs (hard gate skipped %d)",
            len(eligible), len(jobs), len(skipped),
        )
        return {**state, "jobs": eligible + skipped, "error": ""}

    return score


def apply_jobs(state: JobHunterState) -> JobHunterState:
    """Record applications for each eligible job; skip/review jobs are reported."""
    if state.get("error"):
        return state
    resume = state.get("resume_text", "")
    jobs = state.get("jobs", [])
    if not jobs:
        logger.warning("No jobs to apply to")
        return {**state, "applications": [], "error": ""}

    applications: list[dict[str, Any]] = []
    for job in jobs:
        eligibility_decision = job.get("eligibility_decision")
        if eligibility_decision == "skip":
            applications.append({
                "job_id": job.get("id"),
                "job_title": job.get("title"),
                "company": job.get("company"),
                "status": "skipped",
                "detail": "; ".join(job.get("eligibility_reasons", []) or []),
            })
            continue
        if eligibility_decision == "review":
            applications.append({
                "job_id": job.get("id"),
                "job_title": job.get("title"),
                "company": job.get("company"),
                "status": "needs_review",
                "detail": "; ".join(job.get("eligibility_reasons", []) or [])
                or "; ".join(job.get("eligibility_exposed", []) or []),
            })
            continue
        if job.get("discovery_only"):
            # Discovery-only sources (e.g. LinkedIn) are browsable but must never
            # be auto-applied to.
            applications.append({
                "job_id": job.get("id"),
                "job_title": job.get("title"),
                "company": job.get("company"),
                "status": "discovery_only",
                "detail": "Discovery-only source — no application submitted.",
            })
            continue
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

    logger.info("Recorded %d outcomes for %d jobs", len(applications), len(jobs))

    query = state.get("search_query", "")
    submitted = sum(1 for a in applications if a.get("status") in ("applied", "submitted"))
    if applications and query:
        send_job_alert_email(query, len(jobs), submitted)

    return {**state, "applications": applications, "error": ""}


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------
def create_agent(llm: ChatOpenAI | None = None):
    """Build a compiled LangGraph pipeline.

    ``llm`` is injectable for tests; it defaults to the configured chat model.
    """
    llm = llm or _default_llm()

    workflow = StateGraph(JobHunterState)
    workflow.add_node("extract_resume", extract_resume)
    workflow.add_node("generate_query", _make_generate_query(llm))
    workflow.add_node("find_jobs", _make_find_jobs(llm))
    workflow.add_node("build_candidate", build_candidate_knowledge)
    workflow.add_node("assess_eligibility", assess_eligibility)
    workflow.add_node("score_jobs", _make_score_jobs(llm))
    workflow.add_node("apply_jobs", apply_jobs)

    workflow.add_edge(START, "extract_resume")
    workflow.add_edge("extract_resume", "generate_query")
    workflow.add_edge("generate_query", "build_candidate")
    workflow.add_edge("build_candidate", "find_jobs")
    workflow.add_edge("find_jobs", "assess_eligibility")
    workflow.add_edge("assess_eligibility", "score_jobs")
    workflow.add_edge("score_jobs", "apply_jobs")
    workflow.add_edge("apply_jobs", END)

    return workflow.compile()


job_hunter_app = create_agent()


def run_job_hunter(file_path: str, agent: Any = None) -> dict[str, Any]:
    """Execute the full pipeline for a resume PDF and return the final state.

    ``agent`` is optional for testing; defaults to the module-level compiled graph.
    """
    logger.info("Starting JobHunter pipeline for %s", file_path)
    compiled = agent or job_hunter_app
    initial_state: JobHunterState = {
        "file_path": file_path,
        "resume_text": "",
        "search_query": "",
        "candidate": None,
        "jobs": [],
        "applications": [],
        "error": "",
    }
    final_state = compiled.invoke(initial_state)
    logger.info("JobHunter pipeline complete")
    return dict(final_state)
