"""Tests for PDF text extraction."""

from pathlib import Path

import pytest

from jobhunter.core.pdf import extract_text_from_pdf


def test_extracts_text(sample_pdf: Path):
    text = extract_text_from_pdf(str(sample_pdf))
    assert "Software Engineer" in text
    assert "Python" in text


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        extract_text_from_pdf("does-not-exist.pdf")


def test_empty_pdf_is_tolerated(tmp_path: Path):
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"%PDF-1.4\n%%EOF")
    with pytest.raises(Exception):
        extract_text_from_pdf(str(empty))
