from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

try:
    from google.cloud import monitoring_v3
except ImportError:  # pragma: no cover - optional dependency
    monitoring_v3 = None

from retikon_core.logging import get_logger

logger = get_logger(__name__)

_SUBSCRIPTION_RE = re.compile(r"projects/([^/]+)/subscriptions/([^/]+)")


@dataclass(frozen=True)
class SubscriptionTarget:
    modality: str
    project_id: str
    subscription_id: str
    full_name: str


def _default_project_id() -> str | None:
    return (
        os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCLOUD_PROJECT")
        or os.getenv("PROJECT_ID")
    )


def _parse_subscription_target(
    modality: str,
    value: str,
    default_project: str | None,
) -> SubscriptionTarget | None:
    raw = value.strip()
    if not raw:
        return None
    match = _SUBSCRIPTION_RE.search(raw)
    if match:
        project_id, subscription_id = match.group(1), match.group(2)
    else:
        if raw.startswith("projects/"):
            parts = raw.split("/")
            if len(parts) >= 4 and parts[2] == "subscriptions":
                project_id, subscription_id = parts[1], parts[3]
            else:
                return None
        else:
            if not default_project:
                return None
            project_id, subscription_id = default_project, raw
    full_name = f"projects/{project_id}/subscriptions/{subscription_id}"
    return SubscriptionTarget(
        modality=modality,
        project_id=project_id,
        subscription_id=subscription_id,
        full_name=full_name,
    )


def _parse_subscription_map(raw: str) -> list[SubscriptionTarget]:
    if not raw:
        return []
    default_project = _default_project_id()
    items = re.split(r"[;,]", raw)
    targets: list[SubscriptionTarget] = []
    for item in items:
        entry = item.strip()
        if not entry or "=" not in entry:
            continue
        modality, value = entry.split("=", 1)
        modality = modality.strip()
        target = _parse_subscription_target(modality, value, default_project)
        if target is None:
            logger.warning(
                "Queue monitor subscription ignored",
                extra={"modality": modality, "value": value},
            )
            continue
        targets.append(target)
    return targets


def _time_interval(seconds: int = 600) -> monitoring_v3.TimeInterval:
    now = time.time()
    interval = monitoring_v3.TimeInterval()
    interval.end_time.seconds = int(now)
    interval.end_time.nanos = int((now - int(now)) * 1e9)
    interval.start_time.seconds = int(now - seconds)
    interval.start_time.nanos = interval.end_time.nanos
    return interval


def _extract_point_value(points: list[monitoring_v3.Point]) -> float | None:
    if not points:
        return None
    latest = max(points, key=lambda point: point.interval.end_time)
    value = latest.value
    if value is None:
        return None
    if value.int64_value is not None:
        return float(value.int64_value)
    if value.double_value is not None:
        return float(value.double_value)
    return None


class QueueDepthMonitor:
    def __init__(self, targets: list[SubscriptionTarget], interval_seconds: int) -> None:
        self._targets = targets
        self._interval_seconds = max(5, interval_seconds)
        self._lock = threading.Lock()
        self._snapshot: dict[str, Any] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client = monitoring_v3.MetricServiceClient()

    def start(self) -> None:
        if not self._targets:
            return
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._snapshot:
                return None
            return dict(self._snapshot)

    def _run(self) -> None:
        while not self._stop.is_set():
            snapshot = self._poll()
            if snapshot:
                with self._lock:
                    self._snapshot = snapshot
            self._stop.wait(self._interval_seconds)

    def _poll(self) -> dict[str, Any]:
        interval = _time_interval()
        subscriptions: dict[str, dict[str, Any]] = {}
        for target in self._targets:
            backlog = self._fetch_metric(
                target,
                "pubsub.googleapis.com/subscription/num_undelivered_messages",
                interval,
            )
            oldest = self._fetch_metric(
                target,
                "pubsub.googleapis.com/subscription/oldest_unacked_message_age",
                interval,
            )
            if backlog is None and oldest is None:
                continue
            subscriptions[target.modality] = {
                "backlog": int(backlog) if backlog is not None else None,
                "oldest_unacked_s": round(oldest, 2) if oldest is not None else None,
                "subscription": target.full_name,
            }
        if not subscriptions:
            return {}
        return {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "subscriptions": subscriptions,
        }

    def _fetch_metric(
        self,
        target: SubscriptionTarget,
        metric_type: str,
        interval: monitoring_v3.TimeInterval,
    ) -> float | None:
        resource = "pubsub_subscription"
        flt = (
            f'metric.type="{metric_type}" '
            f'AND resource.type="{resource}" '
            f'AND resource.labels.subscription_id="{target.subscription_id}"'
        )
        try:
            series = self._client.list_time_series(
                name=f"projects/{target.project_id}",
                filter=flt,
                interval=interval,
                view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            )
        except Exception as exc:
            logger.warning(
                "Queue monitor query failed",
                extra={
                    "metric_type": metric_type,
                    "subscription": target.full_name,
                    "error_message": str(exc),
                },
            )
            return None
        for item in series:
            value = _extract_point_value(list(item.points))
            if value is not None:
                return value
        return None


def load_queue_monitor() -> QueueDepthMonitor | None:
    if os.getenv("QUEUE_MONITOR_ENABLED", "1") != "1":
        return None
    if monitoring_v3 is None:
        logger.warning("Queue monitor disabled: google-cloud-monitoring not installed")
        return None
    raw = os.getenv("QUEUE_MONITOR_SUBSCRIPTIONS", "").strip()
    targets = _parse_subscription_map(raw)
    if not targets:
        return None
    interval = int(os.getenv("QUEUE_MONITOR_INTERVAL_SECONDS", "30"))
    return QueueDepthMonitor(targets, interval)
