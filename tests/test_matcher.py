"""Tests for job/resume match scoring."""

from jobhunter.domains.matching import compute_match_score, score_jobs

RESUME = (
    "Software Engineer skilled in Python, Docker, AWS, machine learning, "
    "and RAG pipelines with LangChain."
)


def test_high_score_with_matching_skills():
    job = "Python developer needed. Docker, AWS, machine learning, LangChain required."
    score, matched, missing = compute_match_score(job, RESUME)
    assert score > 70
    assert "python" in matched
    assert "docker" in matched


def test_low_score_with_few_matches():
    job = "Java developer for Spring Boot microservices with Kafka."
    score, matched, missing = compute_match_score(job, RESUME)
    assert score < 50
    assert "java" in missing


def test_neutral_when_no_skills_detected():
    score, matched, missing = compute_match_score("Grow your garden", "Hello world")
    assert score == 50
    assert matched == []
    assert missing == []


def test_empty_inputs():
    assert compute_match_score("", "resume")[0] == 0
    assert compute_match_score("job", "")[0] == 0


def test_score_is_bounded():
    score, _, _ = compute_match_score(RESUME, RESUME)
    assert 0 <= score <= 100


def test_score_jobs_sorts_descending():
    jobs = [
        {"id": "1", "title": "Java job", "description": "Java Spring Boot required."},
        {"id": "2", "title": "Python job", "description": "Python machine learning AWS RAG."},
    ]
    scored = score_jobs(jobs, RESUME)
    assert scored[0]["id"] == "2"
    assert scored[0]["match_score"] >= scored[1]["match_score"]
    assert "match_score" in scored[0]
    assert "matched_skills" in scored[0]


class _ScoringLLM:
    """Returns a fixed semantic score on every invoke."""

    def __init__(self, score: str):
        self.score = score

    def invoke(self, prompt: str) -> object:
        return type("Response", (), {"content": self.score})()


def test_score_jobs_blends_semantic_score_when_llm_provided():
    jobs = [{"id": "1", "title": "Python job", "description": "Python machine learning required."}]
    scored = score_jobs(jobs, RESUME, llm=_ScoringLLM("80"))
    assert "semantic_score" in scored[0]
    assert 0 <= scored[0]["match_score"] <= 100


def test_score_jobs_falls_back_when_llm_returns_garbage():
    jobs = [{"id": "1", "title": "Python job", "description": "Python machine learning required."}]
    scored = score_jobs(jobs, RESUME, llm=_ScoringLLM("not-a-number"))
    assert "semantic_score" not in scored[0]
    assert "match_score" in scored[0]
