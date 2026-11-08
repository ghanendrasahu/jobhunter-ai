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
    run_id: str


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
        "Resume",
        "Summary",
        "Experience",
        "Education",
        "Skills",
        "Projects",
        "Certifications",
        "Languages",
        "Interests",
        "Contact",
        "Phone",
        "Email",
        "LinkedIn",
        "GitHub",
        "Portfolio",
        "References",
        "Available",
        "Upon",
        "Request",
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
            from jobhunter.storage.history import resume_id_from_text
            from jobhunter.storage.run_state import record_event, update_run

            plan = build_search_plan(query, candidate=state.get("candidate"), settings=get_settings())
            jobs = search_plan_jobs(plan, run_id=state.get("run_id") or None)
            if state.get("resume_text"):
                update_run(
                    state.get("run_id", ""), resume_id=resume_id_from_text(state["resume_text"]), query=query
                )
            record_event(state.get("run_id", ""), "info", "search", f"Found {len(jobs)} jobs for '{query}'")
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
            len(eligible),
            len(jobs),
            len(skipped),
        )
        return {**state, "jobs": eligible + skipped, "error": ""}

    return score


def _application_explanation(job: dict[str, Any], outcome: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the per-job audit trail: eligibility -> relevance -> application."""
    from jobhunter.automation.apply_contract import apply_portal_for

    return {
        "eligibility": {
            "status": job.get("eligibility_status"),
            "decision": job.get("eligibility_decision"),
            "reasons": list(job.get("eligibility_reasons") or []),
        },
        "relevance": {
            "score": job.get("match_score"),
            "decision": job.get("relevance_decision"),
        },
        "application": {
            "route": apply_portal_for(job),
            "outcome": outcome.get("status") if outcome else None,
        },
    }


def _skipped_outcome(job: dict[str, Any], status: str, detail: str) -> dict[str, Any]:
    return {
        "job_id": job.get("id"),
        "job_title": job.get("title"),
        "company": job.get("company"),
        "status": status,
        "detail": detail,
        "explanation": _application_explanation(job),
    }


def apply_jobs(state: JobHunterState) -> JobHunterState:
    """Consume the PH6-ranked jobs and produce one honest outcome per job.

    Routing (in order):
    1. PH5 ``skip`` -> recorded as skipped; never applied.
    2. PH5 ``review`` -> recorded as needs_review; never applied.
    3. Discovery-only sources -> recorded as discovery_only; never applied.
    4. ``pipeline_apply_mode == "off"`` (default) -> record/open only, no browser.
    5. Otherwise (opt-in ``human``/``auto``) -> supported portals only, in PH6
       ranking order, capped by ``max_applications_per_run``, deduplicated
       against history; submitted only after post-click verification.
    """
    if state.get("error"):
        return state
    resume = state.get("resume_text", "")
    jobs = state.get("jobs", [])
    if not jobs:
        logger.warning("No jobs to apply to")
        return {**state, "applications": [], "error": ""}

    settings = get_settings()
    pipeline_mode = settings.pipeline_apply_mode
    # Local import: jobhunter.automation's package init pulls the browser stack,
    # which imports jobhunter.agent — importing it at module level would cycle.
    from jobhunter.automation.apply_contract import (
        apply_portal_for,
        missing_apply_fields,
        validate_job_contract,
    )

    slots: list[dict[str, Any] | None] = [None] * len(jobs)
    actionable: list[tuple[int, dict[str, Any]]] = []

    for idx, job in enumerate(jobs):
        eligibility_decision = job.get("eligibility_decision")
        if eligibility_decision == "skip":
            slots[idx] = _skipped_outcome(job, "skipped", "; ".join(job.get("eligibility_reasons", []) or []))
            continue
        if eligibility_decision == "review":
            detail = "; ".join(job.get("eligibility_reasons", []) or []) or "; ".join(
                job.get("eligibility_exposed", []) or []
            )
            slots[idx] = _skipped_outcome(job, "needs_review", detail)
            continue
        if job.get("discovery_only"):
            # Discovery-only sources (e.g. LinkedIn, Google Jobs) are browsable
            # but must never be auto-applied to.
            slots[idx] = _skipped_outcome(
                job, "discovery_only", "Discovery-only source — no application submitted."
            )
            continue
        if pipeline_mode == "off":
            # Out-of-the-box behaviour: record the job (portal links open in
            # the user's browser). Nothing is ever submitted from this path.
            try:
                entry = apply_to_job(job, resume)
            except Exception as exc:
                logger.exception("Failed to apply to job %s", job.get("id"))
                entry = {
                    "job_id": job.get("id"),
                    "job_title": job.get("title"),
                    "company": job.get("company"),
                    "status": "failed",
                    "detail": str(exc),
                }
            entry["explanation"] = _application_explanation(job)
            slots[idx] = entry
            continue
        if eligibility_decision != "apply":
            # Opt-in submission requires a positive PH5 verdict; anything else
            # (unknown/missing decision) is never applied.
            slots[idx] = _skipped_outcome(
                job,
                "needs_review",
                f"Eligibility decision {eligibility_decision!r} — not applying.",
            )
            continue
        route = apply_portal_for(job)
        if route is None:
            source = job.get("source") or job.get("portal") or "?"
            slots[idx] = _skipped_outcome(
                job,
                "needs_review",
                f"Source {source!r} has no automated application strategy — refusing to fall through.",
            )
            continue
        missing_contract = validate_job_contract(job)
        if missing_contract:
            slots[idx] = _skipped_outcome(
                job,
                "needs_review",
                f"Search result missing contract keys: {', '.join(missing_contract)}.",
            )
            continue
        missing = missing_apply_fields(job)
        if missing:
            slots[idx] = _skipped_outcome(
                job, "needs_review", f"Job missing required fields: {', '.join(missing)}."
            )
            continue
        actionable.append((idx, job))

    if actionable:
        try:
            from jobhunter.automation.apply_agent import ApplyAgent

            outcomes = ApplyAgent().apply_ranked_jobs(
                [job for _, job in actionable],
                resume,
                candidate=state.get("candidate"),
                mode=pipeline_mode,
                max_applications=settings.max_applications_per_run,
                resume_pdf=state.get("file_path") or None,
                run_id=state.get("run_id") or None,
            )
        except Exception as exc:
            logger.exception("Pipeline auto-apply failed")
            outcomes = [
                {
                    "job_id": job.get("id", "unknown"),
                    "title": job.get("title", ""),
                    "company": job.get("company", ""),
                    "source": job.get("source") or "unknown",
                    "status": "failed",
                    "detail": f"Pipeline auto-apply failed: {exc}",
                }
                for _, job in actionable
            ]
        if len(outcomes) != len(actionable):
            logger.error(
                "apply_ranked_jobs returned %d outcomes for %d jobs — padding safely",
                len(outcomes),
                len(actionable),
            )
            padded = list(outcomes[: len(actionable)])
            while len(padded) < len(actionable):
                job = actionable[len(padded)][1]
                padded.append(
                    {
                        "job_id": job.get("id", "unknown"),
                        "title": job.get("title", ""),
                        "company": job.get("company", ""),
                        "source": job.get("source") or "unknown",
                        "status": "failed",
                        "detail": "Missing outcome for this job — not applied.",
                    }
                )
            outcomes = padded
        for (idx, job), outcome in zip(actionable, outcomes, strict=True):
            entry = dict(outcome)
            entry["explanation"] = _application_explanation(job, outcome)
            slots[idx] = entry

    applications = [slot for slot in slots if slot is not None]
    if state.get("run_id"):
        from jobhunter.storage.run_state import record_application_event

        for entry in applications:
            record_application_event(
                state["run_id"], entry, entry.get("status", "unknown"), entry.get("detail", "")
            )

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

    The run is persisted (``storage/run_state.py``): a run row is opened before
    the graph executes, source metrics and application events are recorded as
    the pipeline progresses, and the run is finished with a summary. Runs that
    die without finishing are marked ``interrupted`` on the next start so a
    crash can never silently re-apply jobs.
    """
    from collections import Counter

    from jobhunter.storage.history import resume_id_from_text
    from jobhunter.storage.run_state import (
        finish_run,
        record_event,
        recover_interrupted_runs,
        start_run,
    )

    logger.info("Starting JobHunter pipeline for %s", file_path)
    recover_interrupted_runs()
    settings = get_settings()
    run_id = start_run(origin="pipeline", mode=settings.pipeline_apply_mode)
    compiled = agent or job_hunter_app
    initial_state: JobHunterState = {
        "file_path": file_path,
        "resume_text": "",
        "search_query": "",
        "candidate": None,
        "jobs": [],
        "applications": [],
        "error": "",
        "run_id": run_id,
    }
    try:
        final_state = compiled.invoke(initial_state)
    except Exception:
        try:
            record_event(run_id, "error", "run", "Pipeline crashed")
            finish_run(run_id, "failed", {"error": "pipeline crashed"})
        except Exception:
            logger.debug("Failed to record run failure", exc_info=True)
        raise

    status = "failed" if final_state.get("error") else "completed"
    applications = final_state.get("applications", [])
    by_status = Counter(a.get("status", "unknown") for a in applications)
    summary: dict[str, Any] = {
        "applications": {
            "total": len(applications),
            "by_status": dict(by_status.most_common()),
            "submitted": sum(by_status[s] for s in ("applied", "submitted")),
        },
    }
    resume_text = final_state.get("resume_text", "")
    if resume_text:
        summary["resume_id"] = resume_id_from_text(resume_text)
    finish_run(run_id, status, summary)
    logger.info("JobHunter pipeline complete (run %s: %s)", run_id, status)
    return dict(final_state)
