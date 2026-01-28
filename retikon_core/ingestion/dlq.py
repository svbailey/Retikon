from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class DlqPayload:
    error_code: str
    error_message: str
    attempt_count: int
    modality: str | None
    gcs_event: dict[str, Any]
    cloudevent: dict[str, Any]
    received_at: str

class NoopDlqPublisher:
    def publish(
        self,
        *,
        error_code: str,
        error_message: str,
        attempt_count: int,
        modality: str | None,
        gcs_event: dict[str, Any],
        cloudevent: dict[str, Any],
    ) -> str:
        _ = DlqPayload(
            error_code=error_code,
            error_message=error_message,
            attempt_count=attempt_count,
            modality=modality,
            gcs_event=gcs_event,
            cloudevent=cloudevent,
            received_at=datetime.now(timezone.utc).isoformat(),
        )
        return "noop"
