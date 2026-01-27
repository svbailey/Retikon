from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from retikon_core.ingestion.eventarc import GcsEvent
from retikon_core.queue import QueuePublisher


@dataclass(frozen=True)
class StreamEvent:
    bucket: str
    name: str
    generation: str
    stream_id: str
    content_type: str | None = None
    size: int | None = None
    device_id: str | None = None
    site_id: str | None = None
    modality: str | None = None
    received_at: str | None = None

    def to_gcs_event(self) -> GcsEvent:
        return GcsEvent(
            bucket=self.bucket,
            name=self.name,
            generation=str(self.generation),
            content_type=self.content_type,
            size=self.size,
            md5_hash=None,
            crc32c=None,
        )


@dataclass(frozen=True)
class StreamDispatchResult:
    accepted: int
    queued: int
    backlog: int
    batch_published: bool
    message_ids: tuple[str, ...]


class StreamBackpressureError(RuntimeError):
    pass


class StreamBatcher:
    def __init__(
        self,
        *,
        max_batch_size: int = 50,
        max_latency_s: float = 2.0,
        max_backlog: int = 1000,
    ) -> None:
        self.max_batch_size = max_batch_size
        self.max_latency_s = max_latency_s
        self.max_backlog = max_backlog
        self._queue: deque[tuple[StreamEvent, float]] = deque()

    @property
    def backlog(self) -> int:
        return len(self._queue)

    def can_accept(self, count: int = 1) -> bool:
        if self.max_backlog <= 0:
            return True
        return (len(self._queue) + count) <= self.max_backlog

    def add(self, event: StreamEvent, now: float | None = None) -> list[StreamEvent]:
        if not self.can_accept():
            raise StreamBackpressureError("Stream backlog exceeded")
        now = time.monotonic() if now is None else now
        self._queue.append((event, now))
        return self._maybe_flush(now)

    def flush(self, now: float | None = None) -> list[StreamEvent]:
        now = time.monotonic() if now is None else now
        return self._maybe_flush(now)

    def _maybe_flush(self, now: float) -> list[StreamEvent]:
        if not self._queue:
            return []
        if len(self._queue) >= self.max_batch_size:
            return self._drain()
        oldest_time = self._queue[0][1]
        if self.max_latency_s <= 0:
            return self._drain()
        if (now - oldest_time) >= self.max_latency_s:
            return self._drain()
        return []

    def _drain(self) -> list[StreamEvent]:
        items = [event for event, _ in self._queue]
        self._queue.clear()
        return items


class StreamIngestPipeline:
    def __init__(
        self,
        *,
        publisher: QueuePublisher,
        topic: str,
        batcher: StreamBatcher,
    ) -> None:
        self.publisher = publisher
        self.topic = topic
        self.batcher = batcher

    def enqueue(
        self,
        event: StreamEvent,
        now: float | None = None,
    ) -> StreamDispatchResult:
        return self.enqueue_events([event], now=now)

    def enqueue_events(
        self, events: Iterable[StreamEvent], now: float | None = None
    ) -> StreamDispatchResult:
        message_ids: list[str] = []
        accepted = 0
        for event in events:
            accepted += 1
            batch = self.batcher.add(event, now=now)
            if batch:
                message_ids.append(self._publish_batch(batch))
        return StreamDispatchResult(
            accepted=accepted,
            queued=accepted,
            backlog=self.batcher.backlog,
            batch_published=bool(message_ids),
            message_ids=tuple(message_ids),
        )

    def flush(self, now: float | None = None) -> tuple[str, ...]:
        batch = self.batcher.flush(now=now)
        if not batch:
            return ()
        message_id = self._publish_batch(batch)
        return (message_id,)

    def _publish_batch(self, events: Sequence[StreamEvent]) -> str:
        payload = {
            "events": [stream_event_to_dict(event) for event in events],
        }
        data = json.dumps(payload).encode("utf-8")
        return self.publisher.publish(topic=self.topic, data=data)


def stream_event_to_dict(event: StreamEvent) -> dict[str, Any]:
    return {
        "bucket": event.bucket,
        "name": event.name,
        "generation": event.generation,
        "stream_id": event.stream_id,
        "content_type": event.content_type,
        "size": event.size,
        "device_id": event.device_id,
        "site_id": event.site_id,
        "modality": event.modality,
        "received_at": event.received_at,
    }


def stream_event_from_dict(payload: dict[str, Any]) -> StreamEvent:
    bucket = payload.get("bucket")
    name = payload.get("name")
    generation = payload.get("generation")
    stream_id = payload.get("stream_id")
    if not bucket or not name or generation is None or not stream_id:
        raise ValueError(
            "Stream event requires bucket, name, generation, and stream_id"
        )
    return StreamEvent(
        bucket=str(bucket),
        name=str(name),
        generation=str(generation),
        stream_id=str(stream_id),
        content_type=payload.get("content_type"),
        size=_coerce_int(payload.get("size")),
        device_id=payload.get("device_id"),
        site_id=payload.get("site_id"),
        modality=payload.get("modality"),
        received_at=payload.get("received_at"),
    )


def decode_stream_batch(data: bytes) -> list[StreamEvent]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Stream batch payload must be JSON") from exc
    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        raise ValueError("Stream batch payload must include events list")
    return [stream_event_from_dict(item) for item in events]


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
