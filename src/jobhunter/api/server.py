"""FastAPI server exposing the JobHunter pipeline as a REST API."""

import logging
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from jobhunter.agent import run_job_hunter
from jobhunter.config import Settings, get_settings

load_dotenv()

logger = logging.getLogger(__name__)

ALLOWED_MIME = "application/pdf"

_UPLOAD_FILE = File(...)  # module-level default to keep FastAPI's call in a default arg


def _validate_pdf(file: UploadFile) -> None:
    """Reject anything that is not a PDF (extension + declared MIME)."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")
    if file.content_type and file.content_type != ALLOWED_MIME:
        raise HTTPException(status_code=400, detail=f"Invalid content type: {file.content_type}")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application.

    ``settings`` is injectable for tests; it defaults to environment config.
    """
    settings = settings or get_settings()
    limiter = Limiter(key_func=get_remote_address)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Upload directory ensured: %s", settings.upload_dir)
        yield

    app = FastAPI(
        title="JobHunter AI Agent",
        version="3.0.0",
        description="Upload a PDF resume to automatically search and apply for matching jobs.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

    async def verify_api_key(x_api_key: str | None = Header(None)) -> None:
        """Reject requests without a valid key when one is configured."""
        if settings.jobhunter_api_key and x_api_key != settings.jobhunter_api_key:
            raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header")

    @app.post("/upload_resume", dependencies=[Depends(verify_api_key)])
    @limiter.limit(settings.api_rate_limit)
    async def upload_resume(request: Request, file: UploadFile = _UPLOAD_FILE) -> JSONResponse:
        """Accept a PDF resume and run the job-hunting pipeline."""
        _validate_pdf(file)

        file_bytes = await file.read()
        if len(file_bytes) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size is {settings.max_file_size_mb} MB.",
            )

        tmp_path = settings.upload_dir / f"{uuid.uuid4()}.pdf"
        try:
            settings.upload_dir.mkdir(parents=True, exist_ok=True)
            tmp_path.write_bytes(file_bytes)
            logger.info("Saved uploaded resume to %s (%d bytes)", tmp_path, len(file_bytes))

            # Run the blocking pipeline in a worker thread to keep the event loop free.
            import asyncio

            result = await asyncio.to_thread(run_job_hunter, str(tmp_path))
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Pipeline execution failed")
            raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}") from exc
        finally:
            tmp_path.unlink(missing_ok=True)

        return JSONResponse(content=result)

    @app.get("/health")
    async def health_check() -> dict:
        """Simple liveness probe."""
        return {"status": "ok", "version": app.version}

    return app


app = create_app()
