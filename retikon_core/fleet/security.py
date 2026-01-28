from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from retikon_core.fleet.types import DeviceRecord, HardeningResult


@dataclass(frozen=True)
class HardeningCheck:
    name: str
    key: str


DEFAULT_CHECKS: tuple[HardeningCheck, ...] = (
    HardeningCheck(name="secure_boot", key="secure_boot"),
    HardeningCheck(name="disk_encryption", key="disk_encryption"),
    HardeningCheck(name="auto_updates", key="auto_updates"),
    HardeningCheck(name="ssh_locked", key="ssh_locked"),
)


def evaluate_hardening(
    settings: dict[str, object] | None,
    *,
    checks: Iterable[HardeningCheck] = DEFAULT_CHECKS,
) -> HardeningResult:
    missing: list[str] = []
    settings = settings or {}
    for check in checks:
        value = settings.get(check.key)
        if value is not True:
            missing.append(check.name)
    status = "pass" if not missing else "fail"
    return HardeningResult(status=status, missing_controls=tuple(missing))


def device_hardening(
    device: DeviceRecord,
    *,
    checks: Iterable[HardeningCheck] = DEFAULT_CHECKS,
) -> HardeningResult:
    metadata = device.metadata or {}
    return evaluate_hardening(metadata, checks=checks)
