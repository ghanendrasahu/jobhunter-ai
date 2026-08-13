"""REST API package. Exposes the FastAPI app for ``uvicorn jobhunter.api:app``."""

from jobhunter.api.server import app, create_app

__all__ = ["app", "create_app"]
