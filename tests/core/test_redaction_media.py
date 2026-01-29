from __future__ import annotations

import pytest

from retikon_core.privacy import build_context, redaction_plan_for_context
from retikon_core.privacy.types import PrivacyPolicy
from retikon_core.redaction import plan_media_redaction, redact_media_payload


@pytest.mark.core
def test_media_redaction_plan_disabled():
    plan = plan_media_redaction(
        modality="image",
        redaction_types=("pii",),
        enabled=False,
    )
    assert plan.applied is False
    assert plan.reason == "disabled"
    assert "face" in plan.resolved_types


@pytest.mark.core
def test_media_redaction_payload_noop():
    payload = b"fake"
    returned, plan = redact_media_payload(
        payload,
        modality="audio",
        redaction_types=("audio_pii",),
        enabled=True,
    )
    assert returned == payload
    assert plan.applied is False
    assert plan.reason == "stub"


@pytest.mark.core
def test_media_redaction_plan_from_privacy_policy():
    policy = PrivacyPolicy(
        id="policy-1",
        name="Image PII",
        org_id=None,
        site_id=None,
        stream_id=None,
        modalities=("image",),
        contexts=("query",),
        redaction_types=("pii",),
        enabled=True,
        created_at="now",
        updated_at="now",
    )
    context = build_context(action="query", modality="image")
    plan = redaction_plan_for_context(
        policies=[policy],
        context=context,
        enabled=True,
    )
    assert plan is not None
    assert plan.modality == "image"
    assert "face" in plan.resolved_types
    assert plan.reason == "stub"
