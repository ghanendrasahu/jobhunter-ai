"""Logging configuration for the jobhunter package.

Sets up the ``jobhunter`` logger subtree with either a human-readable format
(default, local development) or single-line JSON (production / log aggregators,
enabled with ``LOG_JSON=true``). Configuration is idempotent so repeated
imports are safe.
"""

from __future__ import annotations

import json
import logging


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record (timestamp, level, logger, message)."""

    def format(self, record: logging.LogRecord) -> str:
        """Format ``record`` as a single-line JSON string."""
        payload: dict[str, str] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(*, log_json: bool = False) -> None:
    """Configure the ``jobhunter`` logger subtree.

    ``log_json=True`` switches every ``jobhunter.*`` logger to JSON output.
    Re-calling replaces previous handlers instead of duplicating them.
    """
    root = logging.getLogger("jobhunter")
    for handler in list(root.handlers):
        root.removeHandler(handler)
    stream = logging.StreamHandler()
    if log_json:
        stream.setFormatter(JsonFormatter())
    else:
        stream.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
    root.addHandler(stream)
    root.setLevel(logging.INFO)
