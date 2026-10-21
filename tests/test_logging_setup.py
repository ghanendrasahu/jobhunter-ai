"""Tests for JSON structured logging configuration."""

import json
import logging

from jobhunter.logging_setup import JsonFormatter, configure_logging


def _make_record(msg: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="jobhunter.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=None,
    )


def test_json_formatter_emits_valid_json():
    data = json.loads(JsonFormatter().format(_make_record("hello world")))
    assert data["message"] == "hello world"
    assert data["level"] == "INFO"
    assert data["logger"] == "jobhunter.test"
    assert "ts" in data


def test_json_formatter_includes_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        data = json.loads(JsonFormatter().format(_make_record_with_exc()))
    assert "ValueError" in data["exception"]


def _make_record_with_exc():
    import sys

    return logging.LogRecord(
        name="jobhunter.test", level=logging.ERROR, pathname=__file__, lineno=1,
        msg="failed", args=(), exc_info=sys.exc_info(),
    )


def test_configure_logging_json_toggles_formatter():
    try:
        configure_logging(log_json=True)
        root = logging.getLogger("jobhunter")
        assert isinstance(root.handlers[-1].formatter, JsonFormatter)

        configure_logging(log_json=False)
        assert not isinstance(root.handlers[-1].formatter, JsonFormatter)
    finally:
        configure_logging(log_json=False)
