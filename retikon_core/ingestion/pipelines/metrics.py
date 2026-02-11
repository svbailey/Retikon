from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class CallStats:
    calls: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    min_ms: float = 0.0

    def record(self, elapsed_ms: float) -> None:
        self.calls += 1
        self.total_ms += elapsed_ms
        if self.calls == 1 or elapsed_ms < self.min_ms:
            self.min_ms = elapsed_ms
        if elapsed_ms > self.max_ms:
            self.max_ms = elapsed_ms

    def summary(self) -> dict[str, float | int]:
        avg_ms = self.total_ms / self.calls if self.calls else 0.0
        return {
            "calls": self.calls,
            "total_ms": round(self.total_ms, 2),
            "avg_ms": round(avg_ms, 2),
            "max_ms": round(self.max_ms, 2),
            "min_ms": round(self.min_ms, 2),
        }


class CallTracker:
    def __init__(self) -> None:
        self._stats: dict[str, CallStats] = {}
        self._context: dict[str, dict[str, object]] = {}

    def record(self, name: str, elapsed_ms: float) -> None:
        stats = self._stats.setdefault(name, CallStats())
        stats.record(elapsed_ms)

    def set_context(self, name: str, context: dict[str, object]) -> None:
        payload = self._context.setdefault(name, {})
        payload.update(context)

    def summary(self) -> dict[str, dict[str, float | int]]:
        summary: dict[str, dict[str, float | int]] = {}
        for name, stats in self._stats.items():
            payload = stats.summary()
            context = self._context.get(name)
            if context:
                payload.update(context)
            summary[name] = payload
        for name, context in self._context.items():
            if name not in summary:
                summary[name] = dict(context)
        return summary


class StageTimer:
    def __init__(self) -> None:
        self._timings_ms: dict[str, float] = {}

    @contextmanager
    def track(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self._timings_ms[name] = round(
                self._timings_ms.get(name, 0.0) + elapsed_ms,
                2,
            )

    def summary(self) -> dict[str, float]:
        return dict(self._timings_ms)


def timed_call(tracker: CallTracker, name: str, func):
    start = time.perf_counter()
    result = func()
    tracker.record(name, (time.perf_counter() - start) * 1000.0)
    return result


CANONICAL_STAGE_KEYS = (
    "download_ms",
    "decode_ms",
    "extract_audio_ms",
    "extract_frames_ms",
    "vad_ms",
    "transcribe_ms",
    "embed_text_ms",
    "embed_image_ms",
    "embed_audio_ms",
    "write_manifest_ms",
    "write_parquet_ms",
    "write_blobs_ms",
    "finalize_ms",
)


def build_stage_timings(
    raw_timings: dict[str, float],
    mapping: dict[str, str],
) -> dict[str, float]:
    result = {key: 0.0 for key in CANONICAL_STAGE_KEYS}
    for name, duration_ms in raw_timings.items():
        canonical = mapping.get(name)
        if not canonical:
            continue
        result[canonical] += duration_ms
    return {key: round(value, 2) for key, value in result.items()}
