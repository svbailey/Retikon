from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from retikon_core.storage.writer import WriteResult


@dataclass(frozen=True)
class ManifestFile:
    uri: str
    rows: int
    bytes_written: int
    sha256: str


@dataclass(frozen=True)
class ManifestInfo:
    uri: str
    run_id: str
    pipeline_version: str
    schema_version: str
    counts: dict[str, int]
    files: list[ManifestFile]


@dataclass(frozen=True)
class CompactionGroup:
    entity_type: str
    is_edge: bool
    run_id: str
    pipeline_version: str
    schema_version: str
    files: Mapping[str, ManifestFile]

    def file_kinds(self) -> set[str]:
        return set(self.files.keys())

    def bytes_by_kind(self) -> dict[str, int]:
        return {kind: info.bytes_written for kind, info in self.files.items()}

    def rows_by_kind(self) -> dict[str, int]:
        return {kind: info.rows for kind, info in self.files.items()}


@dataclass(frozen=True)
class CompactionBatch:
    entity_type: str
    is_edge: bool
    file_kinds: tuple[str, ...]
    groups: tuple[CompactionGroup, ...]

    def bytes_by_kind(self) -> dict[str, int]:
        totals: dict[str, int] = {kind: 0 for kind in self.file_kinds}
        for group in self.groups:
            for kind, value in group.bytes_by_kind().items():
                if kind in totals:
                    totals[kind] += value
        return totals

    def rows_by_kind(self) -> dict[str, int]:
        totals: dict[str, int] = {kind: 0 for kind in self.file_kinds}
        for group in self.groups:
            for kind, value in group.rows_by_kind().items():
                if kind in totals:
                    totals[kind] += value
        return totals


@dataclass(frozen=True)
class CompactionOutput:
    entity_type: str
    is_edge: bool
    file_kind: str
    result: WriteResult


@dataclass(frozen=True)
class CompactionReport:
    run_id: str
    manifest_uri: str | None
    audit_uri: str | None
    outputs: tuple[CompactionOutput, ...]
    removed_sources: tuple[str, ...]
    counts: dict[str, int]
    started_at: str
    completed_at: str
    duration_seconds: float
