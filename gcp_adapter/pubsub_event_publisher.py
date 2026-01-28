from __future__ import annotations

import json
from typing import Any, Mapping

from google.cloud import pubsub_v1

from retikon_core.webhooks.types import WebhookEvent, event_to_dict


class PubSubEventPublisher:
    def __init__(self) -> None:
        self.client = pubsub_v1.PublisherClient()

    def publish(
        self,
        *,
        topic: str,
        event: WebhookEvent,
        attributes: Mapping[str, str] | None = None,
    ) -> str:
        payload = event_to_dict(event)
        data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        future = self.client.publish(topic, data, **dict(attributes or {}))
        return future.result(timeout=30)

    def publish_json(
        self,
        *,
        topic: str,
        payload: dict[str, Any],
        attributes: Mapping[str, str] | None = None,
    ) -> str:
        data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        future = self.client.publish(topic, data, **dict(attributes or {}))
        return future.result(timeout=30)
