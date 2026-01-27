from __future__ import annotations

from retikon_core.webhooks.delivery import (
    DeliveryOptions,
    DeliveryResult,
    deliver_webhook,
)
from retikon_core.webhooks.logs import WebhookDeliveryRecord
from retikon_core.webhooks.types import WebhookEvent, WebhookRegistration


def send_webhook_event(
    *,
    webhook: WebhookRegistration,
    event: WebhookEvent,
    options: DeliveryOptions | None = None,
) -> tuple[DeliveryResult, list[WebhookDeliveryRecord]]:
    resolved = options or DeliveryOptions()
    return deliver_webhook(webhook, event, resolved)
