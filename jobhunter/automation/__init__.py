"""Application automation: portal login, job evaluation, and (semi-)autonomous applying.

This package implements a human-in-the-loop apply agent:

- **human** mode: the agent opens the job portal, evaluates jobs, pre-fills
  application forms, and leaves submission to you (CAPTCHAs / multi-step ATS).
- **auto** mode: the agent additionally clicks submit.
- **off**: disabled.

The agent logs into Naukri / Indeed with credentials from ``.env`` and reuses the
login session across runs via a persistent browser profile.
"""

from .apply_agent import ApplyAgent, run_application_pipeline

__all__ = ["ApplyAgent", "run_application_pipeline"]
