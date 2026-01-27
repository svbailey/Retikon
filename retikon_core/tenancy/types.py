from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TenantScope:
    org_id: str | None = None
    site_id: str | None = None
    stream_id: str | None = None

    def is_empty(self) -> bool:
        return not any((self.org_id, self.site_id, self.stream_id))
