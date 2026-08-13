"""FastAPI entry point (compatibility shim).

Run with: ``uvicorn app:app --reload --port 8000``
"""

from jobhunter.api.server import app  # noqa: F401
