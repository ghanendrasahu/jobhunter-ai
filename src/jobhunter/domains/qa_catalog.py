"""Curated question-intent catalog for application-form Q&A.

ATS forms ask the same handful of questions in endless phrasings ("How many
years of experience do you have?" vs "Total experience in years"). This module
maps those questions to a canonical :class:`QnAIntent` by curated keyword
phrases (deterministic, offline) — an LLM layer in ``automation.qa`` extends the
mapping to paraphrases the catalog does not cover.

Sensitive intents (legal / demographic / materially sensitive — age, gender,
religion, disability, ...) are flagged so the automatic answering path can
refuse to fill them from the knowledge base. Classification never invents an
intent: unmatched or ambiguous questions classify to ``""`` with
``ambiguous=True`` as appropriate, and callers must then ask the user.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Minimum confidence for an answer to be auto-filled without asking the user.
CONFIDENCE_MIN = 0.75
# Classifications closer together than this are treated as ambiguous.
AMBIGUITY_GAP = 0.1


@dataclass(frozen=True, slots=True)
class QnAIntent:
    """A canonical question intent and its curated phrasings."""

    name: str
    question: str
    variations: tuple[str, ...] = ()
    sensitive: bool = False
    # Which candidate-knowledge field can answer this intent ("" = user only).
    answer_source: str = ""

    def __hash__(self) -> int:  # frozen dataclass keeps default hash
        return super().__hash__()


@dataclass(frozen=True, slots=True)
class IntentClassification:
    """Result of classifying a question text."""

    intent: str = ""
    confidence: float = 0.0
    ambiguous: bool = False
    source: str = "catalog"  # "catalog" | "llm"


INTENT_CATALOG: list[QnAIntent] = [
    QnAIntent("experience_years", "How many years of experience do you have?", (
        "years of experience", "total experience", "overall experience",
        "how many years of experience", "years of work experience",
        "work experience in years", "relevant experience in years",
        "work experience", "overall work experience",
    ), answer_source="experience_years"),
    QnAIntent("current_ctc", "What is your current CTC?", (
        "current ctc", "current salary", "current compensation",
        "present ctc", "present salary", "annual ctc", "current package",
    ), answer_source="current_ctc"),
    QnAIntent("expected_ctc", "What is your expected CTC?", (
        "expected ctc", "expected salary", "expected compensation",
        "desired ctc", "desired salary", "expected package", "salary expectation",
    ), answer_source="expected_ctc"),
    QnAIntent("notice_period", "What is your notice period?", (
        "notice period", "current notice period", "notice period duration",
        "how long is your notice period", "how many days notice period",
    ), answer_source="notice_period"),
    QnAIntent("education", "What is your highest education?", (
        "highest education", "highest qualification", "highest degree",
        "educational qualification", "academic qualification",
    ), answer_source="education"),
    QnAIntent("location_preference", "What is your current location?", (
        "current location", "current city", "present location",
        "where do you currently live", "your location",
    ), answer_source="location"),
    QnAIntent("remote_willingness", "Are you willing to work remotely?", (
        "willing to work remotely", "comfortable working remote",
        "open to remote work", "remote work preference",
        "work from home preference", "remote or onsite",
    ), answer_source="remote_mode"),
    QnAIntent("available_to_start", "When can you join?", (
        "when can you join", "earliest joining date", "availability to join",
        "date of joining", "when can you start", "joining availability",
        "available from",
    )),
    QnAIntent("relocation_willingness", "Are you open to relocation?", (
        "willing to relocate", "open to relocation", "ready to relocate",
        "relocation willingness", "can you relocate",
    )),
    QnAIntent("linkedin_profile", "What is your LinkedIn profile URL?", (
        "linkedin profile", "linkedin url", "linkedin link",
        "share your linkedin",
    ), answer_source="linkedin"),
    QnAIntent("github_profile", "What is your GitHub profile URL?", (
        "github profile", "github url", "github link", "share your github",
    )),
    QnAIntent("skills_summary", "List your key skills.", (
        "key skills", "list your skills", "your technical skills",
        "core skills", "skill set", "technologies known",
    ), answer_source="skills"),
    QnAIntent("work_authorization", "Are you authorized to work in India?", (
        "authorized to work in india", "right to work in india",
        "work authorization in india", "legally authorized to work",
        "eligible to work in india",
    )),
    # --- Sensitive: legal / demographic / materially sensitive --------------
    QnAIntent("date_of_birth", "What is your date of birth?", (
        "date of birth", "dob", "birth date",
    ), sensitive=True),
    QnAIntent("age", "What is your age?", (
        "your age", "how old are you",
    ), sensitive=True),
    QnAIntent("gender", "What is your gender?", (
        "gender", "sex",
    ), sensitive=True),
    QnAIntent("marital_status", "What is your marital status?", (
        "marital status", "marriage status",
    ), sensitive=True),
    QnAIntent("religion", "What is your religion?", ("religion",), sensitive=True),
    QnAIntent("caste", "What is your caste?", ("caste",), sensitive=True),
    QnAIntent("disability_status", "Do you have a disability?", (
        "disability", "differently abled", "handicapped",
    ), sensitive=True),
    QnAIntent("veteran_status", "Are you a veteran?", ("veteran",), sensitive=True),
    QnAIntent("nationality", "What is your nationality?", (
        "nationality", "citizenship", "country of citizenship", "country of origin",
    ), sensitive=True),
    QnAIntent("mother_tongue", "What is your mother tongue?", (
        "mother tongue", "mother language",
    ), sensitive=True),
]

INTENT_BY_NAME: dict[str, QnAIntent] = {intent.name: intent for intent in INTENT_CATALOG}

# Distinctive phrases a compatible form field/label is expected to contain, per
# intent. Used to block answers when the canonical intent does not match the
# *target* field (e.g. an LLM-classified "expected CTC" must never fill a
# notice-period field). Phrases are chosen to be topic-distinctive so that
# superficially similar but materially different questions are rejected.
FIELD_HINTS: dict[str, tuple[str, ...]] = {
    "experience_years": ("experience", "years of experience", "total experience", "work experience", "overall experience", "relevant experience"),
    "current_ctc": ("current ctc", "current salary", "current compensation", "current package", "present ctc", "present salary", "annual ctc", "ctc", "salary", "compensation", "package"),
    "expected_ctc": ("expected ctc", "expected salary", "expected compensation", "expected package", "desired ctc", "desired salary", "salary expectation", "salary", "compensation", "package"),
    "notice_period": ("notice period", "notice"),
    "education": ("education", "educational", "degree", "qualification", "highest qualification"),
    "location_preference": ("current location", "current city", "location", "city", "address", "reside"),
    "remote_willingness": ("remote", "work from home", "wfh", "hybrid", "onsite", "telecommute", "home office"),
    "available_to_start": ("joining", "join", "start date", "date of joining", "when can you", "available to start", "available from"),
    "relocation_willingness": ("relocat", "relocate", "willing to move"),
    "linkedin_profile": ("linkedin", "linked in", "profile url", "profile link"),
    "github_profile": ("github", "git hub", "gitlab"),
    "skills_summary": ("skills", "skill", "technologies", "tech stack", "competencies"),
    "work_authorization": ("authoriz", "right to work", "work permit", "visa", "eligible to work", "legally authorized"),
    "date_of_birth": ("date of birth", "dob", "birthday", "birth date"),
    "age": ("age",),
    "gender": ("gender", "sex"),
    "marital_status": ("marital", "marriage", "married"),
    "religion": ("religion", "religious"),
    "caste": ("caste",),
    "disability_status": ("disability", "disabled", "handicap", "differently abled", "physically challenged"),
    "veteran_status": ("veteran", "military service", "ex-serviceman", "armed forces"),
    "nationality": ("nationality", "citizenship", "citizen", "passport", "country of origin", "country of birth", "born in"),
    "mother_tongue": ("mother tongue", "mother language", "native language", "first language"),
}


def _compact(text: str) -> str:
    """Lowercase and remove all non-alphanumerics for substring matching."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def intent_matches_field(intent: str, field_text: str) -> bool:
    """True when the canonical ``intent`` is compatible with a target field/label.

    Deterministic (no LLM): the normalized field text must contain a distinctive
    hint for the intent. This prevents an answer from being written into a
    materially different application field based on superficial wording.
    """
    hints = FIELD_HINTS.get(intent)
    if not hints:
        return False
    text = _compact(field_text)
    if not text:
        return False
    return any(_compact(hint) and _compact(hint) in text for hint in hints)


def _norm(text: str) -> str:
    """Lowercase and strip to alphanumerics for robust phrase matching."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def classify_by_catalog(question: str) -> IntentClassification:
    """Deterministically map ``question`` to an intent via curated phrases.

    Returns ``intent=""`` for unmatched questions and ``ambiguous=True`` when two
    intents score within :data:`AMBIGUITY_GAP` of each other.
    """
    normalized = _norm(question)
    if not normalized:
        return IntentClassification()

    scores: list[tuple[str, float]] = []
    for intent in INTENT_CATALOG:
        hits = sum(1 for variation in intent.variations if _norm(variation) in normalized)
        if hits:
            scores.append((intent.name, min(0.95, 0.7 + 0.05 * hits)))

    if not scores:
        return IntentClassification()

    scores.sort(key=lambda item: (-item[1], item[0]))
    top, second = scores[0], scores[1] if len(scores) > 1 else None
    if second is not None and (top[1] - second[1]) < AMBIGUITY_GAP:
        return IntentClassification(ambiguous=True, source="catalog")
    return IntentClassification(intent=top[0], confidence=top[1], source="catalog")
