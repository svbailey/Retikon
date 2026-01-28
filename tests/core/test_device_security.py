from __future__ import annotations

import pytest

from retikon_core.fleet.security import device_hardening, evaluate_hardening
from retikon_core.fleet.types import DeviceRecord


@pytest.mark.core
def test_evaluate_hardening():
    result = evaluate_hardening({"secure_boot": True, "disk_encryption": True})
    assert result.status == "fail"
    assert "auto_updates" in result.missing_controls


@pytest.mark.core
def test_device_hardening_pass():
    device = DeviceRecord(
        id="device-1",
        name="Device 1",
        org_id=None,
        site_id=None,
        stream_id=None,
        tags=None,
        status="online",
        firmware_version="1.0.0",
        last_seen_at=None,
        metadata={
            "secure_boot": True,
            "disk_encryption": True,
            "auto_updates": True,
            "ssh_locked": True,
        },
        created_at="now",
        updated_at="now",
    )
    result = device_hardening(device)
    assert result.status == "pass"
    assert result.missing_controls == ()
