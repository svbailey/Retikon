from __future__ import annotations

import pytest

from retikon_core.fleet.rollouts import plan_rollout, rollback_plan
from retikon_core.fleet.types import DeviceRecord


def _device(idx: int) -> DeviceRecord:
    return DeviceRecord(
        id=f"device-{idx}",
        name=f"Device {idx}",
        org_id=None,
        site_id=None,
        stream_id=None,
        tags=None,
        status="online",
        firmware_version=None,
        last_seen_at=None,
        metadata=None,
        created_at="now",
        updated_at="now",
    )


@pytest.mark.core
def test_rollout_plan_stage_distribution():
    devices = [_device(i) for i in range(10)]
    plan = plan_rollout(devices, stage_percentages=[10, 50, 100])
    assert plan.total_devices == 10
    assert len(plan.stages) == 3
    assert len(plan.stages[0].device_ids) == 1
    assert len(plan.stages[1].device_ids) == 4
    assert len(plan.stages[2].device_ids) == 5


@pytest.mark.core
def test_rollout_plan_rollback():
    devices = [_device(i) for i in range(8)]
    plan = plan_rollout(devices, stage_percentages=[25, 50, 100])
    rollback_ids = rollback_plan(plan, stage=2)
    assert len(rollback_ids) == len(plan.stages[1].device_ids) + len(
        plan.stages[2].device_ids
    )
