"""PHASE 4 tests: Q&A memory (persistence, catalog, classification, safety, seam)."""

from __future__ import annotations

import pytest

from jobhunter.automation.form_filler import _fill_control
from jobhunter.automation.qa import QAMemory, classify_question
from jobhunter.domains.candidate import Candidate, Education
from jobhunter.domains.qa_catalog import (
    FIELD_HINTS,
    INTENT_BY_NAME,
    classify_by_catalog,
    intent_matches_field,
)


# ---------------------------------------------------------------------------
# Persistence (storage.qa)
# ---------------------------------------------------------------------------
@pytest.fixture
def qa_store_path(monkeypatch, tmp_path):
    hist = tmp_path / "history"
    monkeypatch.setattr("jobhunter.storage.qa.HISTORY_DIR", hist)
    return hist


def test_save_and_load_roundtrip(qa_store_path):
    from jobhunter.storage import qa as qa_store

    qa_store.save_answer("experience_years", "5 years")
    row = qa_store.load_answer("experience_years")
    assert row is not None
    assert row["intent"] == "experience_years"
    assert row["answer"] == "5 years"
    assert row["source"] == "user"
    assert row["confirmed_at"]


def test_save_upserts_and_empty_deletes(qa_store_path):
    from jobhunter.storage import qa as qa_store

    qa_store.save_answer("notice_period", "30 days")
    qa_store.save_answer("notice_period", "60 days")
    assert qa_store.load_answer("notice_period")["answer"] == "60 days"

    qa_store.save_answer("notice_period", "")
    assert qa_store.load_answer("notice_period") is None


def test_load_all_delete_and_clear(qa_store_path):
    from jobhunter.storage import qa as qa_store

    qa_store.save_answer("current_ctc", "10 LPA")
    qa_store.save_answer("expected_ctc", "15 LPA")
    assert len(qa_store.load_all_answers()) == 2

    qa_store.delete_answer("current_ctc")
    assert qa_store.load_answer("current_ctc") is None
    assert len(qa_store.load_all_answers()) == 1

    qa_store.clear_answers()
    assert qa_store.load_all_answers() == []


def test_storage_persists_across_connections(qa_store_path):
    from jobhunter.storage import qa as qa_store

    qa_store.save_answer("skills_summary", "python")
    del qa_store
    from jobhunter.storage import qa as qa_store2

    assert qa_store2.load_answer("skills_summary")["answer"] == "python"


# ---------------------------------------------------------------------------
# Curated intent catalog (deterministic classification)
# ---------------------------------------------------------------------------
def test_catalog_reworded_questions_same_intent():
    for question in (
        "How many years of experience do you have?",
        "Total experience in years?",
        "Please state your overall work experience.",
        "Years of work experience",
    ):
        result = classify_by_catalog(question)
        assert result.intent == "experience_years", question
        assert result.confidence >= 0.75


def test_catalog_known_questions():
    assert classify_by_catalog("What is your current CTC?").intent == "current_ctc"
    assert classify_by_catalog("Expected salary?").intent == "expected_ctc"
    assert classify_by_catalog("Are you willing to relocate?").intent == "relocation_willingness"
    assert classify_by_catalog("Share your LinkedIn URL").intent == "linkedin_profile"


def test_catalog_unknown_question():
    result = classify_by_catalog("Do you prefer working night shifts?")
    assert result.intent == ""
    assert result.ambiguous is False


def test_catalog_ambiguous_question():
    result = classify_by_catalog("What is your current salary and expected salary?")
    assert result.ambiguous is True


def test_catalog_sensitive_intent_flagged():
    for question, name in (("What is your gender?", "gender"), ("Your date of birth?", "date_of_birth")):
        result = classify_by_catalog(question)
        assert result.intent == name
        assert INTENT_BY_NAME[name].sensitive is True


def test_catalog_dangerous_reworded_question():
    assert classify_by_catalog("What is your country of citizenship?").intent == "nationality"


# ---------------------------------------------------------------------------
# Classification with an LLM (paraphrase gap-fill)
# ---------------------------------------------------------------------------
class _FakeStructuredLLM:
    """Fakes ChatOpenAI.with_structured_output(...) returning an _IntentSchema."""

    def __init__(self, intent, confidence):
        self._intent = intent
        self._confidence = confidence

    def with_structured_output(self, model):
        class _Wrapper:
            def __init__(self, intent, confidence):
                self._intent = intent
                self._confidence = confidence

            def invoke(self, prompt):
                return model(intent=self._intent, confidence=self._confidence)

        return _Wrapper(self._intent, self._confidence)


class _FakePlainLLM:
    """LLM without structured output that returns JSON text."""

    def __init__(self, content):
        self._content = content

    def invoke(self, prompt):
        _FakePlainLLM._Response.content = self._content
        return _FakePlainLLM._Response()

    class _Response:
        content = ""


class _BrokenLLM:
    def invoke(self, prompt):
        raise RuntimeError("llm down")


def test_llm_structured_classifies_paraphrase():
    llm = _FakeStructuredLLM("expected_ctc", 0.95)
    result = classify_question("What salary are you looking for?", llm)
    assert result.intent == "expected_ctc"
    assert result.source == "llm"
    assert result.confidence == 0.95


def test_llm_plain_json_classifies():
    llm = _FakePlainLLM('{"intent": "notice_period", "confidence": 0.9}')
    result = classify_question("What is the duration of your serving notice?", llm)
    assert result.intent == "notice_period"
    assert result.source == "llm"


def test_llm_unknown_intent_ignored():
    result = classify_question("Some entirely new question", _FakeStructuredLLM("unknown", 0.99))
    assert result.intent == ""


def test_llm_invented_intent_ignored():
    result = classify_question("Some entirely new question", _FakeStructuredLLM("favorite_color", 0.9))
    assert result.intent == ""


def test_broken_llm_falls_back_to_catalog():
    result = classify_question("How many years of experience do you have?", _BrokenLLM())
    assert result.intent == "experience_years"


def test_catalog_still_wins_when_confident():
    llm = _FakeStructuredLLM("gender", 0.95)
    result = classify_question("What is your gender?", llm)
    assert result.intent == "gender"
    assert result.source == "catalog"


# ---------------------------------------------------------------------------
# Q&A memory safety and lookup
# ---------------------------------------------------------------------------
def test_answered_from_store(qa_store_path):
    mem = QAMemory()
    mem.record("experience_years", "5 years")
    response = mem.answer_for_question("How many years of experience do you have?")
    assert response.status == "answer"
    assert response.intent == "experience_years"
    assert response.answer == "5 years"
    assert response.reason == "answered"


def test_persistence_across_instances(qa_store_path):
    QAMemory().record("current_ctc", "12 LPA")
    response = QAMemory().answer_for_question("What is your present salary?")
    assert response.status == "answer"
    assert response.answer == "12 LPA"


def test_reworded_question_answered(qa_store_path):
    mem = QAMemory()
    mem.record("expected_ctc", "15 LPA")
    assert mem.answer_for_question("Your expected compensation?").answer == "15 LPA"


def test_unknown_intent_asks_user(qa_store_path):
    response = QAMemory().answer_for_question("Do you prefer working night shifts?")
    assert response.status == "ask_user"
    assert response.reason == "unknown_intent"


def test_ambiguous_question_asks_user(qa_store_path):
    response = QAMemory().answer_for_question("What is your current salary and expected salary?")
    assert response.status == "ask_user"
    assert response.reason == "ambiguous"


def test_low_confidence_asks_user_even_with_stored_answer(qa_store_path):
    mem = QAMemory(llm=_FakeStructuredLLM("current_ctc", 0.4))
    mem.record("current_ctc", "10 LPA")
    response = mem.answer_for_question("What annual package are you currently on?")
    assert response.status == "ask_user"
    assert response.reason == "low_confidence"


def test_sensitive_never_auto_answered(qa_store_path):
    mem = QAMemory()
    mem.record("gender", "Female")
    response = mem.answer_for_question("What is your gender?")
    assert response.status == "ask_user"
    assert response.reason == "sensitive"


def test_dangerous_reworded_question_never_auto_answered(qa_store_path):
    mem = QAMemory()
    mem.record("nationality", "Indian")
    for question in ("What is your country of citizenship?", "Your nationality?", "Country of origin?"):
        response = mem.answer_for_question(question)
        assert response.status == "ask_user", question
        assert response.reason == "sensitive"


def test_no_known_answer_asks_user_not_fabricated(qa_store_path):
    response = QAMemory().answer_for_question("How long is your notice period?")
    assert response.status == "ask_user"
    assert response.reason == "no_known_answer"


def test_record_unknown_intent_refused(qa_store_path):
    mem = QAMemory()
    mem.record("not_an_intent", "whatever")
    assert mem.known_answers() == []


def test_candidate_knowledge_lookup(qa_store_path):
    candidate = Candidate(
        experience_years=5,
        current_ctc="8 LPA",
        location="Bengaluru",
        remote_mode="Remote",
        linkedin="https://linkedin.com/in/candidate",
        skills=["python", "sql"],
        education=[Education(degree="M.Sc Computer Science")],
    )
    mem = QAMemory(candidate=candidate)

    response = mem.answer_for_question("How many years of experience do you have?")
    assert response.status == "answer"
    assert response.answer == "5"

    response = mem.answer_for_question("What is your current city?")
    assert response.status == "answer"
    assert response.answer == "Bengaluru"

    response = mem.answer_for_question("List your key skills")
    assert response.status == "answer"
    assert response.answer == "python, sql"

    response = mem.answer_for_question("What is your highest qualification?")
    assert response.status == "answer"
    assert response.answer == "M.Sc Computer Science"

    response = mem.answer_for_question("Are you willing to work remotely?")
    assert response.status == "answer"
    assert response.answer == "Remote"


def test_candidate_never_fabricates_unknown_fields(qa_store_path):
    mem = QAMemory(candidate=Candidate())
    response = mem.answer_for_question("What is your current CTC?")
    assert response.status == "ask_user"
    assert response.reason == "no_known_answer"


# ---------------------------------------------------------------------------
# Form-filler integration seam (non-invasive, default unchanged)
# ---------------------------------------------------------------------------
class _FakePage:
    def query_selector(self, selector):
        return None


class _FakeHandle:
    def __init__(self, tag="INPUT", attrs=None, options=None, visible=True):
        self._tag = tag
        self._attrs = attrs or {}
        self._options = options or []
        self._visible = visible
        self.page = _FakePage()
        self.filled = None
        self.selected = None

    def get_attribute(self, name):
        return self._attrs.get(name)

    def is_visible(self):
        return self._visible

    def evaluate(self, js):
        if "tagName" in js:
            return self._tag
        if "Array.from(el.options)" in js:
            return list(self._options)
        if "el.name" in js:
            return ""
        return None

    def fill(self, value, timeout=None):
        self.filled = value

    def select_option(self, label=None, timeout=None):
        self.selected = label

    def is_checked(self):
        return False

    def check(self, timeout=None):
        pass


def _stats():
    return {"filled": 0, "skipped": 0, "unknown": 0, "file_uploaded": False, "missing": []}


def test_unknown_control_filled_via_qa(qa_store_path):
    mem = QAMemory()
    mem.record("remote_willingness", "Yes")
    handle = _FakeHandle(attrs={"placeholder": "Work from home preference?"})
    stats = _stats()
    assert _fill_control(handle, {}, None, stats, qa=mem) is True
    assert handle.filled == "Yes"


def test_select_control_filled_via_qa(qa_store_path):
    mem = QAMemory()
    mem.record("remote_willingness", "Yes")
    handle = _FakeHandle(
        tag="SELECT",
        attrs={"placeholder": "Are you comfortable working remote?"},
        options=["Select", "Yes", "No"],
    )
    stats = _stats()
    assert _fill_control(handle, {}, None, stats, qa=mem) is True
    assert handle.selected == "Yes"


def test_qa_ask_user_leaves_control_untouched(qa_store_path):
    mem = QAMemory()
    handle = _FakeHandle(attrs={"placeholder": "Work from home preference?"})
    stats = _stats()
    assert _fill_control(handle, {}, None, stats, qa=mem) is False
    assert handle.filled is None
    assert stats["unknown"] == 1


def test_sensitive_qa_never_fills(qa_store_path):
    mem = QAMemory()
    mem.record("gender", "Female")
    handle = _FakeHandle(attrs={"placeholder": "Gender"})
    stats = _stats()
    assert _fill_control(handle, {}, None, stats, qa=mem) is False
    assert handle.filled is None
    assert stats["unknown"] == 1


def test_no_qa_behaves_unchanged():
    handle = _FakeHandle(attrs={"placeholder": "Work from home preference?"})
    stats = _stats()
    assert _fill_control(handle, {}, None, stats) is False
    assert handle.filled is None
    assert stats["unknown"] == 1


def test_unknown_select_question_never_fabricates(qa_store_path):
    mem = QAMemory()
    handle = _FakeHandle(
        tag="SELECT",
        attrs={"placeholder": "Which city is nearest to you?"},
        options=["Delhi", "Mumbai"],
    )
    stats = _stats()
    assert _fill_control(handle, {}, None, stats, qa=mem) is False
    assert handle.selected is None


# ---------------------------------------------------------------------------
# PHASE 4 safety adjustment: an LLM classification alone must not fill a
# materially different field — the canonical intent must match the target
# field/label. Regression tests for the new compatibility gate.
# ---------------------------------------------------------------------------
def test_intent_matches_field_basics():
    assert intent_matches_field("current_ctc", "What is your current salary?")
    assert intent_matches_field("remote_willingness", "Work from home preference?")
    assert not intent_matches_field("expected_ctc", "Expected notice period")
    assert not intent_matches_field("experience_years", "Years at current employer?")
    assert not intent_matches_field("current_ctc", "Tell us where you reside?")
    assert not intent_matches_field("no_such_intent", "Anything at all")


def test_every_intent_has_field_hints():
    assert set(FIELD_HINTS) == set(INTENT_BY_NAME)


def test_semantically_similar_but_different_question_not_filled(qa_store_path):
    mem = QAMemory(
        llm=_FakeStructuredLLM("experience_years", 0.9),
        candidate=Candidate(experience_years=5),
    )
    handle = _FakeHandle(attrs={"placeholder": "Years at current employer?"})
    stats = _stats()
    assert _fill_control(handle, {}, None, stats, qa=mem) is False
    assert handle.filled is None
    assert stats["unknown"] == 1


def test_wrong_field_llm_classification_not_filled(qa_store_path):
    mem = QAMemory(
        llm=_FakeStructuredLLM("expected_ctc", 0.95),
        candidate=Candidate(expected_ctc="15 LPA"),
    )
    handle = _FakeHandle(attrs={"placeholder": "Your total IT tenure?"})
    stats = _stats()
    assert _fill_control(handle, {}, None, stats, qa=mem) is False
    assert handle.filled is None


def test_ambiguous_llm_classification_asks_user(qa_store_path):
    mem = QAMemory(llm=_FakeStructuredLLM("ambiguous", 0.9))
    response = mem.answer_for_question("What salary range do you want and where are you based?")
    assert response.status == "ask_user"
    assert response.reason == "ambiguous"


def test_safe_canonical_intent_match_fills(qa_store_path):
    mem = QAMemory(
        llm=_FakeStructuredLLM("current_ctc", 0.9),
        candidate=Candidate(current_ctc="8 LPA"),
    )
    handle = _FakeHandle(attrs={"placeholder": "What salary do you currently earn?"})
    stats = _stats()
    assert _fill_control(handle, {}, None, stats, qa=mem) is True
    assert handle.filled == "8 LPA"


def test_sensitive_question_with_stored_answer_asks_user(qa_store_path):
    mem = QAMemory(llm=_FakeStructuredLLM("gender", 0.99))
    mem.record("gender", "Female")
    response = mem.answer_for_question("Please tell us how you identify")
    assert response.status == "ask_user"
    assert response.reason == "sensitive"
