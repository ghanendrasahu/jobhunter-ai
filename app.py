"""FastAPI application exposing the JobHunter AI pipeline as a REST endpoint."""

import os
import uuid
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from agent import run_job_hunter

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
UPLOAD_DIR = "uploads"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_MIME = "application/pdf"
API_KEY = os.getenv("JOBHUNTER_API_KEY", "")

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: ensure upload directory exists."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    logger.info("Upload directory ensured: %s", UPLOAD_DIR)
    yield


app = FastAPI(
    title="JobHunter AI Agent",
    version="2.0.0",
    description="Upload a PDF resume to automatically search and apply for matching jobs.",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Auth dependency (optional – enabled when JOBHUNTER_API_KEY is set)
# ---------------------------------------------------------------------------
async def verify_api_key(x_api_key: str | None = Header(None)) -> None:
    """If an API key is configured, reject requests that don't provide it."""
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid X-API-Key header",
        )


# ---------------------------------------------------------------------------
# File validation
# ---------------------------------------------------------------------------
def _validate_pdf(file: UploadFile) -> None:
    """Check file extension, MIME type, and size."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")
    if file.content_type and file.content_type != ALLOWED_MIME:
        raise HTTPException(status_code=400, detail=f"Invalid content type: {file.content_type}")
    # Size is checked during read to handle streaming


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.post(
    "/upload_resume",
    dependencies=[Depends(verify_api_key)],
)
@limiter.limit("20/minute")
async def upload_resume(
    request: Request,
    file: UploadFile = File(...),
) -> JSONResponse:
    """Accept a PDF resume and run the job-hunting pipeline."""
    _validate_pdf(file)

    # Read file content with size cap
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)} MB.",
        )

    # Write to temporary path
    tmp_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}.pdf")
    try:
        with open(tmp_path, "wb") as buffer:
            buffer.write(file_bytes)
        logger.info("Saved uploaded resume to %s (%d bytes)", tmp_path, len(file_bytes))

        # Run pipeline in a thread pool to avoid blocking the event loop
        import asyncio
        result = await asyncio.to_thread(run_job_hunter, tmp_path)
    except Exception as exc:
        logger.exception("Pipeline execution failed")
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
            logger.debug("Cleaned up temp file: %s", tmp_path)

    return JSONResponse(content=result)


@app.get("/health")
async def health_check() -> dict:
    """Simple liveness probe."""
    return {"status": "ok", "version": app.version}
