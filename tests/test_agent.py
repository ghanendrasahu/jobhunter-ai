"""Tests for the LangGraph agent nodes and pipeline integration."""

import jobhunter.agent as agent
from jobhunter.agent import create_agent, extract_resume, run_job_hunter
from jobhunter.config import Settings


class FakeLLM:
    """Minimal stand-in for a chat model."""

    def __init__(self, content: str = "Python Developer"):
        self.content = content
        self.raise_on_invoke = False

    def invoke(self, prompt: str) -> object:
        if self.raise_on_invoke:
            raise RuntimeError("LLM unavailable")
        return type("Response", (), {"content": self.content})()


def _state(**overrides) -> agent.JobHunterState:
    base = {
        "file_path": "",
        "resume_text": "",
        "search_query": "",
        "jobs": [],
        "applications": [],
        "error": "",
    }
    base.update(overrides)
    return base


def test_extract_resume_success(sample_pdf):
    state = extract_resume(_state(file_path=str(sample_pdf)))
    assert state["error"] == ""
    assert "Software Engineer" in state["resume_text"]


def test_extract_resume_missing_path():
    state = extract_resume(_state())
    assert state["error"]


def test_default_llm_prefers_groq_when_configured(monkeypatch):
    monkeypatch.setattr(
        agent, "get_settings",
        lambda: Settings(groq_api_key="gk-test", groq_model="llama-3.1-8b-instant"),
    )
    llm = agent._default_llm()
    assert llm.openai_api_base == "https://api.groq.com/openai/v1"
    assert llm.model_name == "llama-3.1-8b-instant"


def test_default_llm_falls_back_to_openai(monkeypatch):
    monkeypatch.setattr(
        agent, "get_settings",
        lambda: Settings(openai_api_key="sk-test"),
    )
    llm = agent._default_llm()
    assert llm.openai_api_base is None  # None => OpenAI's default endpoint
    assert llm.model_name == "gpt-4o-mini"


def test_generate_query_uses_llm(sample_resume_text):
    llm = FakeLLM(content="Data Analyst")
    compiled = create_agent(llm=llm)
    result = run_job_hunter("unused.pdf", agent=compiled)  # extraction will fail first

    # Drive the node directly instead of the full graph:
    from jobhunter.agent import _make_generate_query

    node = _make_generate_query(llm)
    state = node(_state(resume_text=sample_resume_text))
    assert state["search_query"] == "Data Analyst"
    assert state["error"] == ""


def test_generate_query_falls_back_when_llm_fails(sample_resume_text):
    llm = FakeLLM()
    llm.raise_on_invoke = True
    node = agent._make_generate_query(llm)
    state = node(_state(resume_text=sample_resume_text))
    assert state["search_query"]  # keyword fallback produced something
    assert state["error"] == ""


def test_full_pipeline_happy_path(sample_pdf, monkeypatch):
    fake_jobs = [
        {"id": "j1", "title": "Python Dev", "company": "Acme", "url": "https://x.com/j1",
         "source": "indeed", "description": "Python required"},
        {"id": "j2", "title": "Data Scientist", "company": "Corp", "url": "https://x.com/j2",
         "source": "linkedin", "description": "Machine learning required"},
    ]

    monkeypatch.setattr(agent, "search_all_jobs", lambda q: fake_jobs)
    monkeypatch.setattr(agent, "apply_to_job", lambda job, resume: {
        "job_id": job["id"], "job_title": job["title"], "company": job["company"],
        "status": "applied", "detail": "ok", "match_score": job.get("match_score"),
    })
    monkeypatch.setattr(agent, "send_job_alert_email", lambda *a, **k: None)

    result = run_job_hunter(str(sample_pdf), agent=create_agent(llm=FakeLLM()))
    assert result["error"] == ""
    assert result["search_query"] == "Python Developer"
    assert len(result["jobs"]) == 2
    assert len(result["applications"]) == 2
    assert all("match_score" in j for j in result["jobs"])


def test_pipeline_propagates_extraction_error(monkeypatch):
    result = run_job_hunter("missing.pdf", agent=create_agent(llm=FakeLLM()))
    assert result["error"]
    assert "Failed to extract resume" in result["error"]
    assert result["jobs"] == []
    assert result["applications"] == []
