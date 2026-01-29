from __future__ import annotations

import os
from typing import Iterable

from retikon_core.privacy.types import PrivacyContext, PrivacyPolicy
from retikon_core.redaction import (
    RedactionPlan,
    media_redaction_enabled,
    plan_media_redaction,
    redact_text,
)
from retikon_core.tenancy.types import TenantScope


def build_context(
    *,
    action: str,
    modality: str | None = None,
    scope: TenantScope | None = None,
    is_admin: bool = False,
) -> PrivacyContext:
    return PrivacyContext(
        action=action.strip().lower(),
        modality=modality.strip().lower() if modality else None,
        scope=scope,
        is_admin=is_admin,
    )


def resolve_redaction_types(
    policies: Iterable[PrivacyPolicy],
    context: PrivacyContext,
) -> tuple[str, ...]:
    requested: list[str] = []
    for policy in policies:
        if not policy.enabled:
            continue
        if not _matches_context(policy, context):
            continue
        if not _matches_scope(policy, context.scope):
            continue
        types = policy.redaction_types or ("pii",)
        for item in types:
            if item not in requested:
                requested.append(item)
    return tuple(requested)


def redact_text_for_context(
    text: str | None,
    *,
    policies: Iterable[PrivacyPolicy],
    context: PrivacyContext,
) -> str | None:
    if text is None:
        return None
    if context.is_admin and _admin_bypass_enabled():
        return text
    redaction_types = resolve_redaction_types(policies, context)
    if not redaction_types:
        return text
    return redact_text(text, redaction_types=redaction_types)


def redaction_plan_for_context(
    *,
    policies: Iterable[PrivacyPolicy],
    context: PrivacyContext,
    enabled: bool | None = None,
) -> RedactionPlan | None:
    if context.modality is None:
        return None
    if context.is_admin and _admin_bypass_enabled():
        return None
    redaction_types = resolve_redaction_types(policies, context)
    if not redaction_types:
        return None
    plan_enabled = media_redaction_enabled() if enabled is None else enabled
    return plan_media_redaction(
        modality=context.modality,
        redaction_types=redaction_types,
        enabled=plan_enabled,
    )


def _admin_bypass_enabled() -> bool:
    return os.getenv("PRIVACY_ADMIN_BYPASS", "0") == "1"


def _matches_context(policy: PrivacyPolicy, context: PrivacyContext) -> bool:
    if policy.contexts:
        contexts = {item.lower() for item in policy.contexts if item}
        if "*" not in contexts and context.action not in contexts:
            return False
    if policy.modalities and context.modality:
        modalities = {item.lower() for item in policy.modalities if item}
        if "*" not in modalities and context.modality not in modalities:
            return False
    elif policy.modalities and not context.modality:
        return False
    return True


def _matches_scope(policy: PrivacyPolicy, scope: TenantScope | None) -> bool:
    if policy.org_id and (scope is None or scope.org_id != policy.org_id):
        return False
    if policy.site_id and (scope is None or scope.site_id != policy.site_id):
        return False
    if policy.stream_id and (scope is None or scope.stream_id != policy.stream_id):
        return False
    return True
