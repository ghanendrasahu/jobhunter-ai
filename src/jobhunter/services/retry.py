"""Bounded retry helper shared by production paths.

Retries are always bounded; there is deliberately no "retry forever" mode.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def call_bounded(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    retryable: tuple[type[BaseException], ...] = (Exception,),
    on_retry: Callable[[int, BaseException], None] | None = None,
    backoff_seconds: float = 0.0,
    sleep: Callable[[float], None] | None = None,
) -> T:
    """Call ``fn`` up to ``attempts`` times; re-raise the last error.

    ``on_retry(attempt, exc)`` is invoked before each retry (1-based attempt
    number); ``backoff_seconds`` is slept between attempts when ``sleep`` is
    provided (defaults are no-op for tests, real sleeps in production).
    """
    attempts = max(1, attempts)
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except retryable as exc:
            last = exc
            if attempt >= attempts:
                break
            if on_retry is not None:
                try:
                    on_retry(attempt, exc)
                except Exception:
                    logger.debug("on_retry callback failed", exc_info=True)
            if backoff_seconds > 0 and sleep is not None:
                try:
                    sleep(backoff_seconds)
                except Exception:
                    logger.debug("sleep interrupted during retry backoff", exc_info=True)
    raise last  # type: ignore[misc]  # last is always set when fn raised
