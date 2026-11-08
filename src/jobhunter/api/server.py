"""FastAPI server exposing the JobHunter pipeline as a REST API."""

import logging
import secrets
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from jobhunter.agent import run_job_hunter
from jobhunter.config import Settings, get_settings, validate_config
from jobhunter.logging_setup import configure_logging

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
    configure_logging(log_json=settings.log_json)

    def rate_limit_key(request: Request) -> str:
        """Rate-limit by real client, not by the trusted proxy's address.

        The last X-Forwarded-For entry is appended by the trusted proxy;
        earlier entries are client-controlled.
        """
        if settings.trust_proxy_headers:
            forwarded = request.headers.get("x-forwarded-for", "")
            if forwarded:
                candidate = forwarded.split(",")[-1].strip()
                if candidate:
                    return candidate
        return get_remote_address(request)

    limiter = Limiter(key_func=rate_limit_key)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            settings.upload_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Upload directory ensured: %s", settings.upload_dir)
        except OSError:
            # Don't crash-loop on an unusable disk: the process starts, /ready
            # reports 503 with the reason, and the orchestrator decides.
            logger.exception("Could not ensure upload directory: %s", settings.upload_dir)
        yield

    app = FastAPI(
        title="JobHunter AI Agent",
        version="3.0.0",
        description="Upload a PDF resume to automatically search and apply for matching jobs.",
        lifespan=lifespan,
    )

    cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    if cors_origins == ["*"]:
        # Wildcard CORS is deliberately dissociated from credentials: browsers
        # reject the combination and it would otherwise leak auth to any site.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    elif cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Apply the fleet's baseline security headers to every response."""
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    app.state.settings = settings
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

    async def verify_api_key(x_api_key: str | None = Header(None)) -> None:
        """Reject requests without a valid key when one is configured."""
        if settings.jobhunter_api_key and not secrets.compare_digest(
            x_api_key or "", settings.jobhunter_api_key
        ):
            raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header")

    @app.post("/upload_resume", dependencies=[Depends(verify_api_key)])
    @limiter.limit(settings.api_rate_limit)
    async def upload_resume(request: Request, file: UploadFile = _UPLOAD_FILE) -> JSONResponse:
        """Accept a PDF resume and run the job-hunting pipeline."""
        _validate_pdf(file)

        file_bytes = await file.read()
        if not file_bytes.startswith(b"%PDF-"):
            raise HTTPException(status_code=400, detail="File is not a valid PDF.")
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
            raise HTTPException(status_code=500, detail="Pipeline failed. Please try again.") from exc
        finally:
            tmp_path.unlink(missing_ok=True)

        return JSONResponse(content=result)

    @app.get("/health")
    async def health_check() -> dict:
        """Simple liveness probe."""
        return {"status": "ok", "version": app.version}

    @app.get("/ready")
    async def readiness_check() -> JSONResponse:
        """Readiness probe: verifies required local state is usable.

        Returns 200 when the service can accept work, 503 with the reasons when
        it cannot (e.g. the upload directory is missing and cannot be created).
        """
        problems: list[str] = []
        try:
            settings.upload_dir.mkdir(parents=True, exist_ok=True)
            probe = settings.upload_dir / ".readiness"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            logger.exception("Readiness probe failed: upload dir unusable")
            problems.append(f"upload dir unusable: {exc}")
        warnings = validate_config(settings)
        for warning in warnings:
            logger.warning("Configuration: %s", warning)
        if problems:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "problems": problems, "warnings": warnings},
            )
        return JSONResponse(content={"status": "ready", "version": app.version, "warnings": warnings})

    return app


app = create_app()
