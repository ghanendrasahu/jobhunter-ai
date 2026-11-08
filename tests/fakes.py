"""Shared test fakes (imported as ``fakes``; pytest puts tests/ on sys.path)."""

from typing import Any

from jobhunter.automation.apply_agent import ApplyAgent
from jobhunter.config import Settings


class FakeLLM:
    def __init__(self, content: str = "Python Developer"):
        self.content = content

    def invoke(self, prompt: str) -> object:
        return type("Response", (), {"content": self.content})()


def job(**overrides) -> dict[str, Any]:
    data = {
        "id": "naukri-abc123",
        "fingerprint": "fp-abc123",
        "title": "Python Developer",
        "company": "Acme",
        "location": "Bengaluru",
        "url": "https://www.naukri.com/job/abc123",
        "source": "naukri",
        "portal": "naukri",
        "description": "Python, Docker, AWS experience required.",
        "required_skills": ["Python"],
        "preferred_skills": [],
        "seniority": "UNKNOWN",
        "discovery_only": False,
        "eligibility_status": "eligible",
        "eligibility_decision": "apply",
        "eligibility_reasons": [],
        "eligibility_exposed": [],
        "eligibility_requirements": [],
        "match_score": 80,
        "relevance_decision": "apply",
    }
    data.update(overrides)
    return data


class FakeSession:
    def __init__(self, fail_start: Exception | None = None):
        self.fail_start = fail_start
        self.started = False
        self.stopped = False
        self.pages: list[object] = []

    def start(self):
        if self.fail_start is not None:
            raise self.fail_start
        self.started = True

    def stop(self):
        self.stopped = True

    def new_tab(self):
        page = object()
        self.pages.append(page)
        return page

    def close_page(self, page):
        pass

    def close_all_pages(self):
        self.pages.clear()


def agent_for(monkeypatch, session, settings=None):
    agent_mod = __import__("jobhunter.automation.apply_agent", fromlist=["ApplyAgent"])
    monkeypatch.setattr(agent_mod, "build_session", lambda settings_, allow_copied_fallback=False: session)
    monkeypatch.setattr(agent_mod, "_default_llm", lambda: object())
    return ApplyAgent(settings=settings or Settings(pipeline_apply_mode="auto"))
