from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Mapping

try:
    from google.cloud import pubsub_v1
except ImportError:  # pragma: no cover - optional dependency
    pubsub_v1 = None

from retikon_core.queue import QueueMessage, QueuePublisher


@dataclass(frozen=True)
class PubSubPushEnvelope:
    message: QueueMessage
    subscription: str | None


class PubSubPublisher(QueuePublisher):
    def __init__(self) -> None:
        if pubsub_v1 is None:
            raise RuntimeError("google-cloud-pubsub is required for Pub/Sub publishing")
        self.client = pubsub_v1.PublisherClient()

    def publish(
        self,
        *,
        topic: str,
        data: bytes,
        attributes: Mapping[str, str] | None = None,
    ) -> str:
        future = self.client.publish(topic, data, **dict(attributes or {}))
        return future.result(timeout=30)

    def publish_json(
        self,
        *,
        topic: str,
        payload: dict[str, Any],
        attributes: Mapping[str, str] | None = None,
    ) -> str:
        data = json.dumps(payload).encode("utf-8")
        return self.publish(topic=topic, data=data, attributes=attributes)


def parse_pubsub_push(body: dict[str, Any]) -> PubSubPushEnvelope:
    message = body.get("message")
    if not isinstance(message, dict):
        raise ValueError("Invalid Pub/Sub push payload: missing message")

    raw_data = message.get("data", "")
    if not isinstance(raw_data, str):
        raise ValueError("Invalid Pub/Sub push payload: data must be base64 string")
    try:
        decoded = base64.b64decode(raw_data)
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError("Invalid Pub/Sub push payload: data not base64") from exc

    attributes = message.get("attributes") or {}
    if not isinstance(attributes, dict):
        raise ValueError("Invalid Pub/Sub push payload: attributes must be object")

    msg = QueueMessage(
        data=decoded,
        attributes={str(k): str(v) for k, v in attributes.items()},
        message_id=message.get("messageId") or message.get("message_id"),
    )
    return PubSubPushEnvelope(message=msg, subscription=body.get("subscription"))
