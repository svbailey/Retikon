from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AdaptiveBatchPolicy:
    min_batch: int = 1
    max_batch: int = 50
    low_watermark: int = 10
    high_watermark: int = 100
    min_delay_ms: int = 0
    max_delay_ms: int = 2000

    def tune(
        self,
        backlog: int,
        avg_latency_ms: float | None = None,
    ) -> tuple[int, int]:
        backlog = max(0, backlog)
        if backlog <= self.low_watermark:
            batch = self.min_batch
            delay = self.min_delay_ms
        elif backlog >= self.high_watermark:
            batch = self.max_batch
            delay = self.max_delay_ms
        else:
            ratio = (backlog - self.low_watermark) / (
                self.high_watermark - self.low_watermark
            )
            batch = int(self.min_batch + ratio * (self.max_batch - self.min_batch))
            delay = int(
                self.min_delay_ms
                + ratio * (self.max_delay_ms - self.min_delay_ms)
            )

        if avg_latency_ms:
            delay = min(self.max_delay_ms, delay + int(avg_latency_ms * 0.25))

        batch = max(self.min_batch, min(self.max_batch, batch))
        delay = max(self.min_delay_ms, min(self.max_delay_ms, delay))
        return batch, delay


@dataclass(frozen=True)
class BackpressurePolicy:
    max_backlog: int = 1000
    hard_limit: int = 2000

    def should_accept(self, backlog: int) -> bool:
        if backlog >= self.hard_limit:
            return False
        return backlog < self.max_backlog
