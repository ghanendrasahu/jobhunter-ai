"""Job evaluation: decide whether to apply to a listing.

Uses the configured LLM (Groq/OpenAI) to reason about the job, with a hard
keyword-scoring fallback so the agent never crashes when the LLM is unavailable.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from jobhunter.core.matcher import compute_match_score

logger = logging.getLogger(__name__)

_DECISION_PROMPT = """You are a job-search assistant. Decide whether the candidate should apply.

Resume:
{resume}

Job:
Title: {title}
Company: {company}
Location: {location}
Description: {description}

Respond with ONLY a JSON object, no markdown:
{{
  "decision": "apply" or "skip",
  "score": 0-100,
  "reason": "one short sentence"
}}
"""


def evaluate_job(job: Dict, resume_text: str, llm: Optional[Any] = None) -> Dict:
    """Return ``{decision, score, reason}`` for a job against a resume."""
    if llm is not None:
        try:
            prompt = _DECISION_PROMPT.format(
                resume=resume_text[:3000],
                title=job.get("title", ""),
                company=job.get("company", ""),
                location=job.get("location", ""),
                description=(job.get("description") or "")[:3000],
            )
            response = llm.invoke(prompt)
            result = _parse_llm_response(response)
            if result:
                return result
        except Exception as exc:
            logger.warning("LLM evaluation failed (%s); using keyword fallback", exc)

    return _fallback_decision(job, resume_text)


def _parse_llm_response(response: Any) -> Optional[Dict]:
    """Extract a valid decision dict from an LLM response, or None."""
    content = (getattr(response, "content", None) or "")
    content = re.sub(r"```(?:json)?", "", content).strip("` \n")
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    decision = str(data.get("decision", "")).strip().lower()
    if decision not in ("apply", "skip"):
        return None
    score = min(max(int(data.get("score", 50)), 0), 100)
    return {
        "decision": decision,
        "score": score,
        "reason": str(data.get("reason", ""))[:200],
    }


def _fallback_decision(job: Dict, resume_text: str) -> Dict:
    """Keyword-based decision: apply when the match score is decent."""
    score, matched, missing = compute_match_score(
        job.get("description", "") or job.get("title", ""), resume_text
    )
    decision = "apply" if score >= 60 else "skip"
    reason = (
        f"Keyword match {score}% (matched: {', '.join(matched[:4]) or 'n/a'}"
        f"; missing: {', '.join(missing[:4]) or 'n/a'})"
    )
    return {"decision": decision, "score": score, "reason": reason}
