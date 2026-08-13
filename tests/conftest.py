"""Shared test fixtures: isolated data dirs and a minimal PDF generator."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Point runtime data dirs at a throwaway location BEFORE any jobhunter import,
# so tests never touch the project's real history/ or resumes/ folders.
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="jobhunter_test_"))
os.environ["HISTORY_DIR"] = str(_TEST_ROOT / "history")
os.environ["RESUMES_DIR"] = str(_TEST_ROOT / "resumes")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JOBHUNTER_API_KEY", "")


def make_pdf(text: str) -> bytes:
    """Build a minimal, valid single-page PDF containing ``text``."""
    content = f"BT /F1 20 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode("latin-1"))
        out.extend(obj)
        out.extend(b"\nendobj\n")

    xref_pos = len(out)
    out.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for off in offsets:
        out.extend(f"{off:010d} 00000 n \n".encode("latin-1"))
    out.extend(b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n")
    out.extend(f"{xref_pos}\n".encode("latin-1"))
    out.extend(b"%%EOF")
    return bytes(out)


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """A valid PDF file containing a realistic resume."""
    path = tmp_path / "resume.pdf"
    resume = (
        "Software Engineer\n"
        "Skills: Python, Machine Learning, Docker, AWS\n"
        "Experience: Built FastAPI services and RAG pipelines with LangChain."
    )
    path.write_bytes(make_pdf(resume))
    return path


@pytest.fixture
def sample_resume_text() -> str:
    return (
        "Software Engineer with experience in Python, FastAPI, Docker and AWS. "
        "Built machine learning and RAG pipelines using LangChain."
    )
