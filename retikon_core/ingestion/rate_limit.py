from __future__ import annotations

import time
from dataclasses import dataclass

from retikon_core.config import Config
from retikon_core.errors import RecoverableError


@dataclass
class TokenBucket:
    capacity: float
    refill_per_sec: float
    tokens: float
    last_refill: float

    def allow(self, cost: float = 1.0) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        if elapsed > 0:
            self.tokens = min(
                self.capacity,
                self.tokens + elapsed * self.refill_per_sec,
            )
            self.last_refill = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False


_BUCKETS: dict[str, TokenBucket] = {}


def _rate_for_modality(config: Config, modality: str) -> int:
    if modality == "document":
        return config.rate_limit_doc_per_min
    if modality == "image":
        return config.rate_limit_image_per_min
    if modality == "audio":
        return config.rate_limit_audio_per_min
    if modality == "video":
        return config.rate_limit_video_per_min
    return 0


def enforce_rate_limit(modality: str, config: Config) -> None:
    rate_per_min = _rate_for_modality(config, modality)
    if rate_per_min <= 0:
        return
    bucket = _BUCKETS.get(modality)
    if bucket is None:
        bucket = TokenBucket(
            capacity=float(rate_per_min),
            refill_per_sec=float(rate_per_min) / 60.0,
            tokens=float(rate_per_min),
            last_refill=time.monotonic(),
        )
        _BUCKETS[modality] = bucket
    if not bucket.allow():
        raise RecoverableError(f"Rate limit exceeded for {modality}")
