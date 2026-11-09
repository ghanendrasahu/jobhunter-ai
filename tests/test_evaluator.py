"""Tests for the job evaluator (LLM + keyword fallback)."""

from jobhunter.automation.evaluator import _fallback_decision, _parse_llm_response, evaluate_job

RESUME = (
    "Software Engineer skilled in Python, FastAPI, Docker, AWS and machine learning. "
    "Built RAG pipelines with LangChain."
)

JOB = {
    "title": "Python Engineer",
    "company": "Acme",
    "location": "Bengaluru",
    "description": "Python, Docker, AWS and machine learning required. LangChain preferred.",
}


def test_llm_apply_decision_is_used():
    class _LLM:
        def invoke(self, prompt):
            return type("R", (), {"content": '{"decision": "apply", "score": 88, "reason": "strong fit"}'})()

    result = evaluate_job(JOB, RESUME, _LLM())
    assert result["decision"] == "apply"
    assert result["score"] == 88
    assert result["reason"] == "strong fit"


def test_llm_skip_decision_is_kept():
    class _LLM:
        def invoke(self, prompt):
            return type(
                "R", (), {"content": '```json\n{"decision": "skip", "score": 20, "reason": "mismatch"}\n```'}
            )()

    result = evaluate_job(JOB, RESUME, _LLM())
    assert result["decision"] == "skip"
    assert result["score"] == 20


def test_llm_failure_uses_keyword_fallback():
    class _Boom:
        def invoke(self, prompt):
            raise RuntimeError("llm unavailable")

    result = evaluate_job(JOB, RESUME, _Boom())
    assert result["decision"] in ("apply", "skip")  # keyword fallback, no exception


def test_llm_garbage_response_uses_fallback():
    class _Garbage:
        def invoke(self, prompt):
            return type("R", (), {"content": "I cannot decide right now, lol"})()

    result = evaluate_job(JOB, RESUME, _Garbage())
    assert result["decision"] in ("apply", "skip")


def test_parse_llm_response_extracts_json_from_prose():
    response = type(
        "R", (), {"content": 'Here is my answer: {"decision": "apply", "score": 61, "reason": "ok"} done'}
    )()
    result = _parse_llm_response(response)
    assert result == {"decision": "apply", "score": 61, "reason": "ok"}


def test_parse_llm_response_rejects_unknown_decision():
    response = type("R", (), {"content": '{"decision": "maybe", "score": 50}'})()
    assert _parse_llm_response(response) is None


def test_parse_llm_response_clamps_score():
    response = type("R", (), {"content": '{"decision": "apply", "score": 140}'})()
    assert _parse_llm_response(response)["score"] == 100


def test_fallback_decision_applies_on_good_match():
    job = {"title": "Python Engineer", "description": "Python, Docker, AWS, machine learning required."}
    result = _fallback_decision(job, RESUME)
    assert result["decision"] == "apply"
    assert result["score"] >= 60


def test_fallback_decision_skips_on_poor_match():
    job = {"title": "Java Developer", "description": "Java Spring Boot microservices with Kafka and Redis."}
    result = _fallback_decision(job, RESUME)
    assert result["decision"] == "skip"


def test_no_llm_falls_back_to_keywords():
    result = evaluate_job(JOB, RESUME, None)
    assert result["decision"] in ("apply", "skip")
    assert 0 <= result["score"] <= 100
