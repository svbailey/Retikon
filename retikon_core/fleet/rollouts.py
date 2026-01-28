from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

from retikon_core.fleet.types import DeviceRecord, RolloutPlan, RolloutStage


@dataclass(frozen=True)
class RolloutInput:
    stage_percentages: tuple[int, ...]
    max_per_stage: int | None


def _normalize_percentages(values: Sequence[int] | None) -> tuple[int, ...]:
    if not values:
        return (10, 50, 100)
    cleaned: list[int] = []
    for raw in values:
        try:
            pct = int(raw)
        except (TypeError, ValueError):
            continue
        pct = max(1, min(100, pct))
        if pct not in cleaned:
            cleaned.append(pct)
    cleaned.sort()
    if cleaned and cleaned[-1] != 100:
        cleaned.append(100)
    return tuple(cleaned or (100,))


def _device_ids(devices: Iterable[DeviceRecord]) -> list[str]:
    return sorted([device.id for device in devices])


def plan_rollout(
    devices: Iterable[DeviceRecord],
    *,
    stage_percentages: Sequence[int] | None = None,
    max_per_stage: int | None = None,
) -> RolloutPlan:
    ids = _device_ids(devices)
    total = len(ids)
    percentages = _normalize_percentages(stage_percentages)

    stages: list[RolloutStage] = []
    prior_count = 0
    for idx, percent in enumerate(percentages, start=1):
        target = int(math.ceil((percent / 100.0) * total))
        target = min(target, total)
        if max_per_stage is not None:
            target = min(target, prior_count + max_per_stage)
        target = max(target, prior_count)
        stage_ids = ids[prior_count:target]
        stages.append(
            RolloutStage(
                stage=idx,
                percent=percent,
                target_count=target,
                device_ids=tuple(stage_ids),
            )
        )
        prior_count = target
        if prior_count >= total:
            break

    return RolloutPlan(total_devices=total, stages=tuple(stages))


def rollback_plan(plan: RolloutPlan, *, stage: int) -> tuple[str, ...]:
    if stage <= 1:
        return ()
    if stage > len(plan.stages):
        return ()
    rollback: list[str] = []
    for stage_info in plan.stages[stage - 1 :]:
        rollback.extend(stage_info.device_ids)
    return tuple(rollback)
