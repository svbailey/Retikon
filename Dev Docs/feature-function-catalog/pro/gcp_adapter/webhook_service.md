# gcp_adapter/webhook_service.py

Edition: Pro

## Functions
- `health`: Reports service health, so webhooks and alerts are managed.
- `list_webhooks`: Function that lists webhooks, so webhooks and alerts are managed.
- `create_webhook`: Function that creates webhook, so webhooks and alerts are managed.
- `list_alerts`: Function that lists alerts, so webhooks and alerts are managed.
- `create_alert`: Function that creates alert, so webhooks and alerts are managed.
- `dispatch_event`: Function that dispatches event, so webhooks and alerts are managed.
- `_get_config`: Internal helper that gets config, so webhooks and alerts are managed.
- `_delivery_options`: Internal helper that delivery options, so webhooks and alerts are managed.
- `_logs_enabled`: Internal helper that checks whether logs is enabled, so webhooks and alerts are managed.
- `_webhook_response`: Internal helper that webhook response, so webhooks and alerts are managed.
- `_alert_response`: Internal helper that alert response, so webhooks and alerts are managed.
- `_resolve_webhooks`: Internal helper that resolves webhooks, so webhooks and alerts are managed.
- `_resolve_pubsub_topics`: Internal helper that resolves Pub/Sub topics, so webhooks and alerts are managed.
- `_accepts_event`: Internal helper that accepts event, so webhooks and alerts are managed.
- `_publish_pubsub`: Internal helper that sends Pub/Sub, so webhooks and alerts are managed.

## Classes
- `HealthResponse`: Data structure or helper class for Health Response, so webhooks and alerts are managed.
- `WebhookCreateRequest`: Data structure or helper class for Webhook Create Request, so webhooks and alerts are managed.
- `WebhookResponse`: Data structure or helper class for Webhook Response, so webhooks and alerts are managed.
- `AlertDestinationRequest`: Data structure or helper class for Alert Destination Request, so webhooks and alerts are managed.
- `AlertCreateRequest`: Data structure or helper class for Alert Create Request, so webhooks and alerts are managed.
- `AlertResponse`: Data structure or helper class for Alert Response, so webhooks and alerts are managed.
- `EventRequest`: Data structure or helper class for Event Request, so webhooks and alerts are managed.
- `EventDeliveryResponse`: Data structure or helper class for Event Delivery Response, so webhooks and alerts are managed.
