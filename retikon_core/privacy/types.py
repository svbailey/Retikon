from __future__ import annotations

from dataclasses import dataclass

from retikon_core.tenancy.types import TenantScope


@dataclass(frozen=True)
class PrivacyPolicy:
    id: str
    name: str
    org_id: str | None
    site_id: str | None
    stream_id: str | None
    modalities: tuple[str, ...] | None
    contexts: tuple[str, ...] | None
    redaction_types: tuple[str, ...] | None
    enabled: bool
    created_at: str
    updated_at: str
    status: str = "active"


@dataclass(frozen=True)
class PrivacyContext:
    action: str
    modality: str | None = None
    scope: TenantScope | None = None
    is_admin: bool = False

    def with_modality(self, modality: str | None) -> "PrivacyContext":
        return PrivacyContext(
            action=self.action,
            modality=modality,
            scope=self.scope,
            is_admin=self.is_admin,
        )
