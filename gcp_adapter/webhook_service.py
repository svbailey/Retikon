import os
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from gcp_adapter.pubsub_event_publisher import PubSubEventPublisher
from retikon_core.alerts import evaluate_rules, load_alerts, register_alert
from retikon_core.alerts.types import AlertDestination, AlertRule
from retikon_core.config import get_config
from retikon_core.logging import configure_logging, get_logger
from retikon_core.webhooks.delivery import (
    DeliveryOptions,
    DeliveryResult,
    deliver_webhook,
)
from retikon_core.webhooks.logs import (
    WebhookDeliveryRecord,
    write_webhook_delivery_log,
)
from retikon_core.webhooks.store import load_webhooks, register_webhook
from retikon_core.webhooks.types import WebhookEvent, WebhookRegistration

SERVICE_NAME = "retikon-webhooks"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)

app = FastAPI()


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    commit: str
    timestamp: str


class WebhookCreateRequest(BaseModel):
    name: str
    url: str
    secret: str | None = None
    event_types: list[str] | None = None
    enabled: bool = True
    headers: dict[str, str] | None = None
    timeout_s: float | None = None


class WebhookResponse(BaseModel):
    id: str
    name: str
    url: str
    event_types: list[str] | None = None
    enabled: bool
    created_at: str
    updated_at: str
    headers: dict[str, str] | None = None
    timeout_s: float | None = None


class AlertDestinationRequest(BaseModel):
    kind: str
    target: str
    attributes: dict[str, str] | None = None


class AlertCreateRequest(BaseModel):
    name: str
    event_types: list[str] | None = None
    modalities: list[str] | None = None
    min_confidence: float | None = None
    tags: list[str] | None = None
    destinations: list[AlertDestinationRequest] = Field(default_factory=list)
    enabled: bool = True


class AlertResponse(BaseModel):
    id: str
    name: str
    event_types: list[str] | None = None
    modalities: list[str] | None = None
    min_confidence: float | None = None
    tags: list[str] | None = None
    destinations: list[AlertDestinationRequest]
    enabled: bool
    created_at: str
    updated_at: str


class EventRequest(BaseModel):
    event_type: str
    payload: dict[str, Any]
    modality: str | None = None
    confidence: float | None = None
    tags: list[str] | None = None
    source: str | None = None
    webhook_ids: list[str] | None = None
    pubsub_topics: list[str] | None = None


class EventDeliveryResponse(BaseModel):
    event_id: str
    deliveries: int
    successes: int
    failures: int
    pubsub_published: int
    log_uri: str | None = None


def _correlation_id(header_value: str | None) -> str:
    if header_value:
        return header_value
    return str(uuid.uuid4())


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    corr = _correlation_id(request.headers.get("x-correlation-id"))
    request.state.correlation_id = corr
    response = await call_next(request)
    response.headers["x-correlation-id"] = corr
    return response


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    version = os.getenv("RETIKON_VERSION", "dev")
    commit = os.getenv("GIT_COMMIT", "unknown")
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=version,
        commit=commit,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


@app.get("/webhooks", response_model=list[WebhookResponse])
async def list_webhooks(request: Request) -> list[WebhookResponse]:
    config = _get_config()
    webhooks = load_webhooks(config.graph_root_uri())
    return [_webhook_response(hook) for hook in webhooks]


@app.post("/webhooks", response_model=WebhookResponse, status_code=201)
async def create_webhook(
    request: Request,
    payload: WebhookCreateRequest,
) -> WebhookResponse:
    config = _get_config()
    webhook = register_webhook(
        base_uri=config.graph_root_uri(),
        name=payload.name,
        url=payload.url,
        secret=payload.secret,
        event_types=payload.event_types,
        enabled=payload.enabled,
        headers=payload.headers,
        timeout_s=payload.timeout_s,
    )
    logger.info(
        "Webhook registered",
        extra={
            "request_id": str(uuid.uuid4()),
            "correlation_id": request.state.correlation_id,
            "status": "created",
        },
    )
    return _webhook_response(webhook)


@app.get("/alerts", response_model=list[AlertResponse])
async def list_alerts(request: Request) -> list[AlertResponse]:
    config = _get_config()
    rules = load_alerts(config.graph_root_uri())
    return [_alert_response(rule) for rule in rules]


@app.post("/alerts", response_model=AlertResponse, status_code=201)
async def create_alert(request: Request, payload: AlertCreateRequest) -> AlertResponse:
    config = _get_config()
    destinations = tuple(
        AlertDestination(
            kind=item.kind,
            target=item.target,
            attributes=item.attributes,
        )
        for item in payload.destinations
    )
    rule = register_alert(
        base_uri=config.graph_root_uri(),
        name=payload.name,
        event_types=payload.event_types,
        modalities=payload.modalities,
        min_confidence=payload.min_confidence,
        tags=payload.tags,
        destinations=destinations,
        enabled=payload.enabled,
    )
    logger.info(
        "Alert rule registered",
        extra={
            "request_id": str(uuid.uuid4()),
            "correlation_id": request.state.correlation_id,
            "status": "created",
        },
    )
    return _alert_response(rule)


@app.post("/events", response_model=EventDeliveryResponse, status_code=202)
async def dispatch_event(
    request: Request,
    payload: EventRequest,
    x_request_id: str | None = Header(default=None),
) -> EventDeliveryResponse:
    config = _get_config()
    event_id = str(uuid.uuid4())
    event = WebhookEvent(
        id=event_id,
        event_type=payload.event_type,
        created_at=datetime.now(timezone.utc).isoformat(),
        payload=payload.payload,
        modality=payload.modality,
        confidence=payload.confidence,
        tags=tuple(payload.tags) if payload.tags else None,
        source=payload.source,
    )
    webhooks = load_webhooks(config.graph_root_uri())
    rules = load_alerts(config.graph_root_uri())

    target_webhooks = _resolve_webhooks(
        webhooks,
        event.event_type,
        payload.webhook_ids,
        rules,
        event,
    )
    pubsub_topics = _resolve_pubsub_topics(payload.pubsub_topics, rules, event)

    options = _delivery_options()
    results: list[DeliveryResult] = []
    records: list[WebhookDeliveryRecord] = []
    for webhook in target_webhooks:
        hook_options = options
        if webhook.timeout_s is not None:
            hook_options = replace(options, timeout_s=webhook.timeout_s)
        result, attempt_records = deliver_webhook(webhook, event, hook_options)
        results.append(result)
        records.extend(attempt_records)

    published = _publish_pubsub(event, pubsub_topics)

    log_uri = None
    if records and _logs_enabled():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        run_id = f"webhook-{timestamp}-{uuid.uuid4()}"
        log_uri = write_webhook_delivery_log(
            base_uri=config.graph_root_uri(),
            run_id=run_id,
            records=records,
        )

    successes = sum(1 for result in results if result.status == "success")
    failures = sum(1 for result in results if result.status == "failed")

    logger.info(
        "Event dispatched",
        extra={
            "request_id": x_request_id or event_id,
            "correlation_id": request.state.correlation_id,
            "status": "completed",
            "duration_ms": 0,
        },
    )

    return EventDeliveryResponse(
        event_id=event_id,
        deliveries=len(results),
        successes=successes,
        failures=failures,
        pubsub_published=published,
        log_uri=log_uri,
    )


def _get_config():
    try:
        return get_config()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _delivery_options() -> DeliveryOptions:
    return DeliveryOptions(
        timeout_s=float(os.getenv("WEBHOOK_TIMEOUT_S", "10")),
        max_attempts=int(os.getenv("WEBHOOK_MAX_ATTEMPTS", "3")),
        backoff_s=float(os.getenv("WEBHOOK_BACKOFF_S", "0.5")),
    )


def _logs_enabled() -> bool:
    return os.getenv("WEBHOOK_LOGS_ENABLED", "1") == "1"


def _webhook_response(webhook: WebhookRegistration) -> WebhookResponse:
    return WebhookResponse(
        id=webhook.id,
        name=webhook.name,
        url=webhook.url,
        event_types=list(webhook.event_types) if webhook.event_types else None,
        enabled=webhook.enabled,
        created_at=webhook.created_at,
        updated_at=webhook.updated_at,
        headers=webhook.headers,
        timeout_s=webhook.timeout_s,
    )


def _alert_response(rule: AlertRule) -> AlertResponse:
    return AlertResponse(
        id=rule.id,
        name=rule.name,
        event_types=list(rule.event_types) if rule.event_types else None,
        modalities=list(rule.modalities) if rule.modalities else None,
        min_confidence=rule.min_confidence,
        tags=list(rule.tags) if rule.tags else None,
        destinations=[
            AlertDestinationRequest(
                kind=dest.kind,
                target=dest.target,
                attributes=dest.attributes,
            )
            for dest in rule.destinations
        ],
        enabled=rule.enabled,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _resolve_webhooks(
    webhooks: list[WebhookRegistration],
    event_type: str,
    explicit_ids: list[str] | None,
    rules: list[AlertRule],
    event: WebhookEvent,
) -> list[WebhookRegistration]:
    if explicit_ids:
        target_ids = set(explicit_ids)
    else:
        matches = evaluate_rules(event, rules)
        target_ids = {
            dest.target
            for match in matches
            for dest in match.destinations
            if dest.kind == "webhook"
        }
        if not matches:
            target_ids = {
                hook.id
                for hook in webhooks
                if _accepts_event(hook, event_type)
            }

    resolved: list[WebhookRegistration] = []
    seen: set[str] = set()
    for hook in webhooks:
        if hook.id in target_ids and _accepts_event(hook, event_type):
            if hook.id in seen:
                continue
            resolved.append(hook)
            seen.add(hook.id)
    return resolved


def _resolve_pubsub_topics(
    explicit_topics: list[str] | None,
    rules: list[AlertRule],
    event: WebhookEvent,
) -> list[str]:
    if explicit_topics:
        return list({topic for topic in explicit_topics if topic})
    matches = evaluate_rules(event, rules)
    topics = {
        dest.target
        for match in matches
        for dest in match.destinations
        if dest.kind == "pubsub"
    }
    return [topic for topic in topics if topic]


def _accepts_event(webhook: WebhookRegistration, event_type: str) -> bool:
    if not webhook.event_types:
        return True
    if "*" in webhook.event_types:
        return True
    return event_type in webhook.event_types


def _publish_pubsub(event: WebhookEvent, topics: list[str]) -> int:
    if not topics:
        return 0
    publisher = PubSubEventPublisher()
    published = 0
    for topic in topics:
        publisher.publish(topic=topic, event=event)
        published += 1
    return published
