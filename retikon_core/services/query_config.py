from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryServiceConfig:
    max_query_bytes: int
    max_image_base64_bytes: int
    slow_query_ms: int
    log_query_timings: bool
    query_warmup: bool
    query_warmup_text: str
    query_warmup_steps: set[str]
    query_trace_hitlists: bool
    query_trace_hitlist_size: int

    @classmethod
    def from_env(cls) -> "QueryServiceConfig":
        trace_size_raw = os.getenv("QUERY_TRACE_HITLIST_SIZE", "5")
        try:
            trace_size = int(trace_size_raw)
        except ValueError:
            trace_size = 5
        if trace_size < 1:
            trace_size = 1
        return cls(
            max_query_bytes=int(os.getenv("MAX_QUERY_BYTES", "4000000")),
            max_image_base64_bytes=int(os.getenv("MAX_IMAGE_BASE64_BYTES", "2000000")),
            slow_query_ms=int(os.getenv("SLOW_QUERY_MS", "2000")),
            log_query_timings=os.getenv("LOG_QUERY_TIMINGS", "0") == "1",
            query_warmup=os.getenv("QUERY_WARMUP", "1") == "1",
            query_warmup_text=os.getenv("QUERY_WARMUP_TEXT", "retikon warmup"),
            query_warmup_steps={
                step.strip().lower()
                for step in os.getenv(
                    "QUERY_WARMUP_STEPS",
                    "text,image_text,audio_text,image",
                ).split(",")
                if step.strip()
            },
            query_trace_hitlists=os.getenv("QUERY_TRACE_HITLISTS", "1") == "1",
            query_trace_hitlist_size=trace_size,
        )
