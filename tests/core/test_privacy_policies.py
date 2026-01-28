from __future__ import annotations

import pytest

from retikon_core.privacy import (
    build_context,
    load_privacy_policies,
    redact_text_for_context,
    register_privacy_policy,
)
from retikon_core.privacy.types import PrivacyPolicy
from retikon_core.tenancy.types import TenantScope


@pytest.mark.core
def test_privacy_policy_roundtrip(tmp_path):
    policy = register_privacy_policy(
        base_uri=tmp_path.as_posix(),
        name="PII Redaction",
        org_id="org-1",
        modalities=["document"],
        contexts=["query"],
    )
    loaded = load_privacy_policies(tmp_path.as_posix())
    assert loaded
    assert loaded[0].id == policy.id
    assert loaded[0].org_id == "org-1"
    assert loaded[0].modalities == ("document",)
    assert loaded[0].contexts == ("query",)
    assert loaded[0].redaction_types == ("pii",)


@pytest.mark.core
def test_privacy_policy_applies_redaction_by_scope():
    policy = PrivacyPolicy(
        id="policy-1",
        name="Scope",
        org_id="org-1",
        site_id=None,
        stream_id=None,
        modalities=("document",),
        contexts=("query",),
        redaction_types=("pii",),
        enabled=True,
        created_at="now",
        updated_at="now",
    )
    context = build_context(
        action="query",
        modality="document",
        scope=TenantScope(org_id="org-1"),
        is_admin=False,
    )
    redacted = redact_text_for_context(
        "email test@example.com",
        policies=[policy],
        context=context,
    )
    assert "test@example.com" not in redacted

    other = build_context(
        action="query",
        modality="document",
        scope=TenantScope(org_id="org-2"),
        is_admin=False,
    )
    untouched = redact_text_for_context(
        "email test@example.com",
        policies=[policy],
        context=other,
    )
    assert untouched == "email test@example.com"


@pytest.mark.core
def test_privacy_admin_bypass(monkeypatch):
    policy = PrivacyPolicy(
        id="policy-2",
        name="Admin",
        org_id=None,
        site_id=None,
        stream_id=None,
        modalities=("document",),
        contexts=("query",),
        redaction_types=("pii",),
        enabled=True,
        created_at="now",
        updated_at="now",
    )
    monkeypatch.setenv("PRIVACY_ADMIN_BYPASS", "1")
    context = build_context(
        action="query",
        modality="document",
        scope=None,
        is_admin=True,
    )
    text = "email test@example.com"
    assert (
        redact_text_for_context(text, policies=[policy], context=context) == text
    )
