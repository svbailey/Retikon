from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from retikon_core.webhooks.logs import WebhookDeliveryRecord
from retikon_core.webhooks.signer import sign_payload
from retikon_core.webhooks.types import WebhookEvent, WebhookRegistration, event_to_dict


@dataclass(frozen=True)
class DeliveryOptions:
    timeout_s: float = 10.0
    max_attempts: int = 3
    backoff_s: float = 0.5
    retry_statuses: tuple[int, ...] = (429, 500, 502, 503, 504)


@dataclass(frozen=True)
class DeliveryResult:
    webhook_id: str
    event_id: str
    status: str
    status_code: int | None
    attempts: int
    duration_ms: int
    error: str | None = None


def deliver_webhook(
    webhook: WebhookRegistration,
    event: WebhookEvent,
    options: DeliveryOptions,
) -> tuple[DeliveryResult, list[WebhookDeliveryRecord]]:
    if not webhook.enabled:
        result = DeliveryResult(
            webhook_id=webhook.id,
            event_id=event.id,
            status="skipped",
            status_code=None,
            attempts=0,
            duration_ms=0,
        )
        return result, []

    body = json.dumps(event_to_dict(event), ensure_ascii=True).encode("utf-8")
    timestamp = datetime.now(timezone.utc).isoformat()
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Retikon-Webhooks/1.0",
        "X-Retikon-Event": event.event_type,
        "X-Retikon-Event-Id": event.id,
        "X-Retikon-Timestamp": timestamp,
    }
    if webhook.secret:
        headers["X-Retikon-Signature"] = sign_payload(webhook.secret, timestamp, body)
    if webhook.headers:
        headers.update(webhook.headers)

    delivery_id = str(uuid.uuid4())
    attempts = 0
    started = time.monotonic()
    records: list[WebhookDeliveryRecord] = []
    last_error: str | None = None
    last_status: int | None = None

    while attempts < max(1, options.max_attempts):
        attempts += 1
        attempt_start = time.monotonic()
        status: str
        status_code: int | None = None
        error: str | None = None
        try:
            request = Request(webhook.url, data=body, headers=headers, method="POST")
            with urlopen(request, timeout=options.timeout_s) as response:
                status_code = getattr(response, "status", None) or response.getcode()
                status = "success" if 200 <= status_code < 300 else "failed"
        except HTTPError as exc:
            status_code = exc.code
            status = "failed"
            error = exc.reason if isinstance(exc.reason, str) else str(exc)
        except URLError as exc:
            status = "failed"
            error = str(exc)
        except Exception as exc:  # pragma: no cover - defensive
            status = "failed"
            error = str(exc)

        duration_ms = int((time.monotonic() - attempt_start) * 1000)
        records.append(
            WebhookDeliveryRecord(
                delivery_id=delivery_id,
                event_id=event.id,
                webhook_id=webhook.id,
                attempt=attempts,
                status=status,
                status_code=status_code,
                error=error,
                duration_ms=duration_ms,
                delivered_at=datetime.now(timezone.utc).isoformat(),
            )
        )

        last_error = error
        last_status = status_code

        if status == "success":
            total_ms = int((time.monotonic() - started) * 1000)
            result = DeliveryResult(
                webhook_id=webhook.id,
                event_id=event.id,
                status="success",
                status_code=status_code,
                attempts=attempts,
                duration_ms=total_ms,
            )
            return result, records

        if not _should_retry(status_code, options.retry_statuses):
            break

        if attempts < options.max_attempts and options.backoff_s > 0:
            time.sleep(options.backoff_s * (2 ** (attempts - 1)))

    total_ms = int((time.monotonic() - started) * 1000)
    result = DeliveryResult(
        webhook_id=webhook.id,
        event_id=event.id,
        status="failed",
        status_code=last_status,
        attempts=attempts,
        duration_ms=total_ms,
        error=last_error,
    )
    return result, records


def deliver_webhooks(
    webhooks: Iterable[WebhookRegistration],
    event: WebhookEvent,
    options: DeliveryOptions,
) -> tuple[list[DeliveryResult], list[WebhookDeliveryRecord]]:
    results: list[DeliveryResult] = []
    records: list[WebhookDeliveryRecord] = []
    for webhook in webhooks:
        result, attempts = deliver_webhook(webhook, event, options)
        results.append(result)
        records.extend(attempts)
    return results, records


def _should_retry(status_code: int | None, retry_statuses: tuple[int, ...]) -> bool:
    if status_code is None:
        return True
    return status_code in retry_statuses
