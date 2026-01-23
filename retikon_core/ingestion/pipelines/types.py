from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineResult:
    counts: dict[str, int]
    manifest_uri: str
