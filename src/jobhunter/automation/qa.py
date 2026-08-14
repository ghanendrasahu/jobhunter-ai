"""Q&A memory: classify a form question, look up a confirmed answer, or ask.

The service glues together:

- :mod:`jobhunter.domains.qa_catalog` — curated intents + deterministic classifier.
- :mod:`jobhunter.storage.qa` — persistent, candidate-confirmed answers.
- :mod:`jobhunter.domains.candidate` — structured candidate knowledge (PHASE 3).

Safety contract (never fabricate):

- UNKNOWN / ambiguous / low-confidence intents → ``ask_user``.
- Sensitive intents (legal, demographic, materially sensitive) are NEVER
  auto-answered from the knowledge base, regardless of stored answers — only
  an explicit user answer at fill time is acceptable.
- Answers are only returned when they actually exist in a known source.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from jobhunter.domains.candidate import Candidate
from jobhunter.domains.qa_catalog import (
    CONFIDENCE_MIN,
    INTENT_BY_NAME,
    IntentClassification,
    QnAIntent,
    classify_by_catalog,
)
from jobhunter.storage import qa as qa_store

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class QnAResponse:
    """Result of answering a form question."""

    status: str  # "answer" | "ask_user"
    intent: str
    confidence: float
    answer: str
    reason: str  # answered | unknown_intent | ambiguous | low_confidence | sensitive | no_known_answer


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
def classify_question(question: str, llm=None) -> IntentClassification:
    """Classify ``question`` into a curated intent, catalog-first with LLM gap-fill.

    The deterministic catalog handles known phrasings; when it cannot reach the
    confidence threshold, an LLM is consulted (when available) to catch
    paraphrases. The LLM result is accepted when it names a valid intent; its
    confidence is preserved so the safety layer can still refuse low-confidence
    answers.
    """
    catalog = classify_by_catalog(question)
    if catalog.confidence >= CONFIDENCE_MIN and not catalog.ambiguous:
        return catalog

    if llm is not None:
        llm_result = _classify_with_llm(question, llm)
        if llm_result is not None and llm_result.confidence > 0 and (llm_result.intent or llm_result.ambiguous):
            return llm_result

    return catalog


def _classify_with_llm(question: str, llm) -> IntentClassification | None:
    """LLM classification via structured output (falling back to JSON). Never raises."""
    structured = getattr(llm, "with_structured_output", None)
    if callable(structured):
        try:
            output = structured(_IntentSchema)
            result = output.invoke(_LLM_CLASSIFY_PROMPT.format(intents=_intent_listing(), question=question))
            intent = str(getattr(result, "intent", "") or "")
            confidence = float(getattr(result, "confidence", 0) or 0)
            return _llm_classification(intent, confidence)
        except Exception as exc:
            logger.debug("Structured LLM classification failed: %s", exc)

    try:
        response = llm.invoke(_LLM_CLASSIFY_PROMPT.format(intents=_intent_listing(), question=question))
        content = _response_text(response)
        start, end = content.find("{"), content.rfind("}")
        data = json.loads(content[start:end + 1]) if start >= 0 and end > start else {}
        intent = str(data.get("intent", "") or "")
        confidence = float(data.get("confidence", 0) or 0)
        return _llm_classification(intent, confidence)
    except Exception as exc:
        logger.debug("Plain LLM classification failed: %s", exc)
        return None


def _llm_classification(intent: str, confidence: float) -> IntentClassification | None:
    """Validate an LLM classification against the catalog."""
    name = intent.strip().lower()
    confidence = min(max(confidence, 0.0), 1.0)
    if name == "ambiguous":
        return IntentClassification(ambiguous=True, confidence=confidence, source="llm")
    if name in INTENT_BY_NAME:
        return IntentClassification(intent=name, confidence=confidence, source="llm")
    return None


def _intent_listing() -> str:
    lines = []
    for intent in INTENT_BY_NAME.values():
        lines.append(f"- {intent.name}: {intent.question}")
    return "\n".join(lines)


_LLM_CLASSIFY_PROMPT = """You classify questions that a job application form asks a candidate.

Classify the question into exactly one of these intents:
{intents}

Rules:
- If the question does not match any intent, respond with "unknown".
- If it matches two or more intents equally, respond with "ambiguous".
- Never invent an intent name.

Respond with ONLY a JSON object: {{"intent": "<intent_name|unknown|ambiguous>", "confidence": <0.0 to 1.0>}}

Question: {question}"""


def _response_text(response: Any) -> str:
    content = getattr(response, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content or "")


class _IntentSchema(BaseModel):
    """Structured-output schema for LLM intent classification."""

    intent: str
    confidence: float


# ---------------------------------------------------------------------------
# Q&A memory service
# ---------------------------------------------------------------------------
class QAMemory:
    """Persistent Q&A memory with classification, lookup, and safety rules."""

    def __init__(
        self,
        llm=None,
        candidate: Candidate | None = None,
        profile: dict | None = None,
    ) -> None:
        self._llm = llm
        self._candidate = candidate
        self._profile = profile or {}

    # -- writes -------------------------------------------------------------
    def record(self, intent: str, answer: str, source: str = "user") -> None:
        """Persist the candidate's confirmed answer for ``intent``."""
        if intent not in INTENT_BY_NAME:
            logger.warning("Refusing to store answer for unknown intent %r", intent)
            return
        try:
            qa_store.save_answer(intent, answer, source)
        except Exception as exc:
            logger.warning("Failed to persist Q&A answer: %s", exc)

    def known_answers(self) -> list[dict]:
        """Every persisted Q&A answer."""
        try:
            return qa_store.load_all_answers()
        except Exception as exc:
            logger.warning("Failed to load Q&A answers: %s", exc)
            return []

    # -- reads --------------------------------------------------------------
    def answer_for_question(self, question: str) -> QnAResponse:
        """Answer a form question from memory/knowledge, or ask the user.

        Never fabricates: an answer is returned only when it exists in the
        persisted store or the candidate knowledge base.
        """
        classification = classify_question(question, self._llm)

        if classification.ambiguous:
            return QnAResponse("ask_user", "", 0.0, "", "ambiguous")

        intent = INTENT_BY_NAME.get(classification.intent)
        if intent is None:
            return QnAResponse("ask_user", "", classification.confidence, "", "unknown_intent")

        if classification.confidence < CONFIDENCE_MIN:
            return QnAResponse("ask_user", intent.name, classification.confidence, "", "low_confidence")

        if intent.sensitive:
            return QnAResponse("ask_user", intent.name, classification.confidence, "", "sensitive")

        answer = self._stored_answer(intent.name)
        if not answer:
            answer = self._candidate_answer(intent)
        if not answer:
            return QnAResponse("ask_user", intent.name, classification.confidence, "", "no_known_answer")

        return QnAResponse("answer", intent.name, classification.confidence, answer, "answered")

    def _stored_answer(self, intent: str) -> str:
        try:
            row = qa_store.load_answer(intent)
        except Exception as exc:
            logger.debug("Failed to load Q&A answer for %s: %s", intent, exc)
            return ""
        return (row or {}).get("answer", "") or ""

    def _candidate_answer(self, intent: QnAIntent) -> str:
        """Answer from candidate knowledge (PHASE 3) where the intent maps to one."""
        c = self._candidate
        p = self._profile
        source = intent.answer_source
        if source == "experience_years":
            return str(c.experience_years) if c and c.experience_years is not None else ""
        if source == "current_ctc":
            return _first(c and c.current_ctc, p.get("current_ctc"))
        if source == "expected_ctc":
            return _first(c and c.expected_ctc, p.get("expected_ctc"))
        if source == "notice_period":
            return _first(c and c.notice_period, p.get("notice_period"))
        if source == "linkedin":
            return _first(c and c.linkedin, p.get("linkedin"))
        if source == "education":
            if c and c.education:
                return c.education[0].degree
            value = p.get("education")
            return value if isinstance(value, str) else ""
        if source == "location":
            return _first(c and c.location, p.get("location"))
        if source == "remote_mode":
            return (c and c.remote_mode) or ""
        if source == "skills":
            if c and c.skills:
                return ", ".join(c.skills)
            return ", ".join(str(s) for s in p.get("skills", [])) if p.get("skills") else ""
        return ""


def _first(*values: object) -> str:
    """Return the first non-empty string value."""
    for value in values:
        if value:
            return str(value)
    return ""
