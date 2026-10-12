# app/retry.py

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def retry_operation(
    operation: Callable[[], T],
    *,
    max_attempts: int = 3,
    base_delay: float = 0.25,
    sleep: Callable[[float], None] = time.sleep,
    retry_on: tuple[type[Exception], ...] = (Exception,),
) -> T:
    """Run ``operation`` with bounded retries and exponential backoff.

    Only exceptions listed in ``retry_on`` are retried; anything else
    propagates immediately. After ``max_attempts`` the last error is raised.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    for attempt in range(max_attempts):
        try:
            return operation()
        except retry_on:
            if attempt == max_attempts - 1:
                raise
            sleep(base_delay * (2**attempt))

    raise RuntimeError("Operation failed unexpectedly")
