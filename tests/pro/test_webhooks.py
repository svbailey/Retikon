from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError

from fastapi.testclient import TestClient

from retikon_core.config import get_config
from retikon_core.webhooks.delivery import DeliveryOptions, deliver_webhook
from retikon_core.webhooks.logs import WebhookDeliveryRecord
from retikon_core.webhooks.signer import sign_payload
from retikon_core.webhooks.types import WebhookEvent, WebhookRegistration


def test_webhook_delivery_signing(monkeypatch):
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["body"] = request.data

        class DummyResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def getcode(self):
                return 200

        return DummyResponse()

    monkeypatch.setattr("retikon_core.webhooks.delivery.urlopen", fake_urlopen)

    webhook = WebhookRegistration(
        id="wh_1",
        name="Test",
        url="https://example.com/hook",
        secret="secret",
        event_types=None,
        enabled=True,
        created_at="now",
        updated_at="now",
    )
    event = WebhookEvent(
        id="evt_1",
        event_type="asset.processed",
        created_at="2026-01-27T00:00:00Z",
        payload={"ok": True},
    )
    options = DeliveryOptions(timeout_s=1, max_attempts=1, backoff_s=0)
    result, _records = deliver_webhook(webhook, event, options)
    assert result.status == "success"

    request = captured["request"]
    body = captured["body"]
    combined_headers = dict(request.headers)
    combined_headers.update(getattr(request, "unredirected_hdrs", {}))
    timestamp = (
        combined_headers.get("X-Retikon-Timestamp")
        or combined_headers.get("X-retikon-timestamp")
        or combined_headers.get("x-retikon-timestamp")
    )
    signature = (
        combined_headers.get("X-Retikon-Signature")
        or combined_headers.get("X-retikon-signature")
        or combined_headers.get("x-retikon-signature")
    )
    assert timestamp
    assert signature
    assert signature == sign_payload("secret", timestamp, body)


def test_webhook_delivery_retries(monkeypatch):
    calls: list[int] = []

    def fake_urlopen(request, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise HTTPError(request.full_url, 500, "boom", hdrs=None, fp=None)

        class DummyResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def getcode(self):
                return 200

        return DummyResponse()

    monkeypatch.setattr("retikon_core.webhooks.delivery.urlopen", fake_urlopen)

    webhook = WebhookRegistration(
        id="wh_2",
        name="Retry",
        url="https://example.com/retry",
        secret=None,
        event_types=None,
        enabled=True,
        created_at="now",
        updated_at="now",
    )
    event = WebhookEvent(
        id="evt_2",
        event_type="alert.triggered",
        created_at="2026-01-27T00:00:00Z",
        payload={"ok": True},
    )
    options = DeliveryOptions(timeout_s=1, max_attempts=2, backoff_s=0)
    result, _records = deliver_webhook(webhook, event, options)
    assert result.status == "success"
    assert result.attempts == 2


def test_webhook_service_dispatch_writes_log(tmp_path, monkeypatch, jwt_headers):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_GRAPH_ROOT", tmp_path.as_posix())
    get_config.cache_clear()

    import gcp_adapter.webhook_service as service

    importlib.reload(service)

    def fake_deliver(webhook, event, options):
        record = WebhookDeliveryRecord(
            delivery_id="delivery-1",
            event_id=event.id,
            webhook_id=webhook.id,
            attempt=1,
            status="success",
            status_code=200,
            error=None,
            duration_ms=5,
            delivered_at=datetime.now(timezone.utc).isoformat(),
        )
        result = service.DeliveryResult(
            webhook_id=webhook.id,
            event_id=event.id,
            status="success",
            status_code=200,
            attempts=1,
            duration_ms=5,
        )
        return result, [record]

    monkeypatch.setattr(service, "deliver_webhook", fake_deliver)

    client = TestClient(service.app, headers=jwt_headers)
    resp = client.post(
        "/webhooks",
        json={"name": "Demo", "url": "https://example.com/hook"},
    )
    assert resp.status_code == 201

    event_resp = client.post(
        "/events",
        json={"event_type": "asset.ready", "payload": {"ok": True}},
    )
    assert event_resp.status_code == 202
    payload = event_resp.json()
    assert payload["deliveries"] == 1
    assert payload["successes"] == 1
    assert payload["log_uri"]

    log_path = Path(payload["log_uri"])
    assert log_path.exists()
    get_config.cache_clear()
