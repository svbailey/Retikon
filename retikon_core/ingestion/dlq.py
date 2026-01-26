from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

try:
    from google.cloud import pubsub_v1
except ImportError:  # pragma: no cover - optional dependency
    pubsub_v1 = None

from retikon_core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class DlqPayload:
    error_code: str
    error_message: str
    attempt_count: int
    modality: str | None
    gcs_event: dict[str, Any]
    cloudevent: dict[str, Any]
    received_at: str


class DlqPublisher:
    def __init__(self, topic: str) -> None:
        if pubsub_v1 is None:
            raise RuntimeError("google-cloud-pubsub is required for DLQ publishing")
        self.topic = topic
        self.client = pubsub_v1.PublisherClient()

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
        payload = DlqPayload(
            error_code=error_code,
            error_message=error_message,
            attempt_count=attempt_count,
            modality=modality,
            gcs_event=gcs_event,
            cloudevent=cloudevent,
            received_at=datetime.now(timezone.utc).isoformat(),
        )
        data = json.dumps(payload.__dict__).encode("utf-8")
        future = self.client.publish(self.topic, data)
        message_id = future.result(timeout=30)
        logger.info(
            "Published DLQ message",
            extra={
                "error_code": error_code,
                "attempt_count": attempt_count,
                "modality": modality,
            },
        )
        return message_id
