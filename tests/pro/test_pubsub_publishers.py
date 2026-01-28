from __future__ import annotations

import json

from gcp_adapter.dlq_pubsub import PubSubDlqPublisher
from gcp_adapter.pubsub_event_publisher import PubSubEventPublisher
from retikon_core.webhooks.types import WebhookEvent


class _FakeFuture:
    def __init__(self, message_id: str):
        self._message_id = message_id

    def result(self, timeout=None):
        return self._message_id


class _FakePublisher:
    def __init__(self):
        self.calls = []

    def publish(self, topic, data, **attrs):
        self.calls.append((topic, data, attrs))
        return _FakeFuture("msg-1")


def test_dlq_pubsub_publisher(monkeypatch):
    fake = _FakePublisher()
    monkeypatch.setattr(
        "gcp_adapter.dlq_pubsub.pubsub_v1.PublisherClient",
        lambda: fake,
    )

    publisher = PubSubDlqPublisher("projects/x/topics/dlq")
    message_id = publisher.publish(
        error_code="PERMANENT",
        error_message="oops",
        attempt_count=1,
        modality="document",
        gcs_event={"bucket": "b", "name": "n", "generation": "1"},
        cloudevent={"id": "evt"},
    )
    assert message_id == "msg-1"
    assert fake.calls
    topic, data, _attrs = fake.calls[0]
    assert topic == "projects/x/topics/dlq"
    payload = json.loads(data.decode("utf-8"))
    assert payload["error_code"] == "PERMANENT"


def test_pubsub_event_publisher(monkeypatch):
    fake = _FakePublisher()
    monkeypatch.setattr(
        "gcp_adapter.pubsub_event_publisher.pubsub_v1.PublisherClient",
        lambda: fake,
    )

    publisher = PubSubEventPublisher()
    event = WebhookEvent(
        id="evt_1",
        event_type="asset.processed",
        created_at="2026-01-27T00:00:00Z",
        payload={"ok": True},
    )
    message_id = publisher.publish(
        topic="projects/x/topics/events",
        event=event,
        attributes={"tenant": "t1"},
    )
    assert message_id == "msg-1"
    topic, data, attrs = fake.calls[0]
    assert topic == "projects/x/topics/events"
    assert attrs["tenant"] == "t1"
    payload = json.loads(data.decode("utf-8"))
    assert payload["type"] == "asset.processed"
