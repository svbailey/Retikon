from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Callable, TypeVar

from retikon_core.errors import InferenceTimeoutError

_T = TypeVar("_T")

def _worker_count() -> int:
    raw = os.getenv("MODEL_INFERENCE_WORKERS", "4")
    try:
        value = int(raw)
    except ValueError:
        value = 4
    return max(1, value)


_EXECUTOR = ThreadPoolExecutor(max_workers=_worker_count())


def _parse_timeout(value: str | None) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def inference_timeout_seconds(kind: str) -> float:
    normalized = kind.strip().lower()
    key = f"MODEL_INFERENCE_{normalized.upper()}_TIMEOUT_S"
    specific = _parse_timeout(os.getenv(key))
    if specific > 0:
        return specific
    # Backward compatibility for rerank-specific timeout configuration.
    if normalized == "rerank":
        legacy = _parse_timeout(os.getenv("RERANK_TIMEOUT_S"))
        if legacy > 0:
            return legacy
    return _parse_timeout(os.getenv("MODEL_INFERENCE_TIMEOUT_S", "0"))


def run_inference(kind: str, fn: Callable[[], _T]) -> _T:
    timeout_s = inference_timeout_seconds(kind)
    if timeout_s <= 0:
        return fn()
    future = _EXECUTOR.submit(fn)
    try:
        return future.result(timeout=timeout_s)
    except FutureTimeoutError as exc:
        raise InferenceTimeoutError(
            f"{kind} inference timed out after {timeout_s:.2f}s"
        ) from exc
