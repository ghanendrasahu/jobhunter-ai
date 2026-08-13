"""PDF text extraction."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader

logger = logging.getLogger(__name__)


@lru_cache(maxsize=32)
def extract_text_from_pdf(file_path: str) -> str:
    """Extract and concatenate the text of every page in a PDF.

    The result is cached by file path so repeated reads of the same resume
    (e.g. dashboard refreshes) do not re-parse the file.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {file_path}")

    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(pages)
    logger.info("Extracted %d characters from %s", len(text), file_path)
    return text
