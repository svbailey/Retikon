from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Sequence

from retikon_core.compaction.types import CompactionBatch, CompactionGroup


@dataclass(frozen=True)
class CompactionPolicy:
    target_min_bytes: int = 100 * 1024 * 1024
    target_max_bytes: int = 1024 * 1024 * 1024
    max_groups_per_batch: int = 50

    @classmethod
    def from_env(cls) -> "CompactionPolicy":
        def _env_int(name: str, default: int) -> int:
            raw = os.getenv(name)
            if not raw:
                return default
            try:
                return int(raw)
            except ValueError as exc:
                raise ValueError(f"{name} must be an integer") from exc

        return cls(
            target_min_bytes=_env_int(
                "COMPACTION_TARGET_MIN_BYTES", 100 * 1024 * 1024
            ),
            target_max_bytes=_env_int(
                "COMPACTION_TARGET_MAX_BYTES", 1024 * 1024 * 1024
            ),
            max_groups_per_batch=_env_int("COMPACTION_MAX_GROUPS_PER_BATCH", 50),
        )

    def plan(
        self,
        *,
        groups: Sequence[CompactionGroup],
        file_kinds: Sequence[str],
    ) -> list[CompactionBatch]:
        if not groups:
            return []
        if not file_kinds:
            return []

        batches: list[CompactionBatch] = []
        current: list[CompactionGroup] = []
        running_bytes: dict[str, int] = {kind: 0 for kind in file_kinds}

        def flush() -> None:
            nonlocal current, running_bytes
            if not current:
                return
            batches.append(
                CompactionBatch(
                    entity_type=current[0].entity_type,
                    is_edge=current[0].is_edge,
                    file_kinds=tuple(file_kinds),
                    groups=tuple(current),
                )
            )
            current = []
            running_bytes = {kind: 0 for kind in file_kinds}

        for group in groups:
            group_bytes = group.bytes_by_kind()
            projected = {
                kind: running_bytes.get(kind, 0) + group_bytes.get(kind, 0)
                for kind in file_kinds
            }
            projected_max = max(projected.values())
            if current and (
                projected_max > self.target_max_bytes
                or len(current) >= self.max_groups_per_batch
            ):
                flush()
                projected = {
                    kind: group_bytes.get(kind, 0) for kind in file_kinds
                }
                projected_max = max(projected.values())

            current.append(group)
            running_bytes = projected
            if projected_max >= self.target_min_bytes:
                flush()

        flush()
        return batches
