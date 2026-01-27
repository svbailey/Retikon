from __future__ import annotations

from typing import Mapping

import pytest

from retikon_core.ingestion.streaming import (
    StreamBackpressureError,
    StreamBatcher,
    StreamEvent,
    StreamIngestPipeline,
    decode_stream_batch,
)
from retikon_core.queue import QueuePublisher


class FakePublisher(QueuePublisher):
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes, Mapping[str, str] | None]] = []

    def publish(
        self,
        *,
        topic: str,
        data: bytes,
        attributes: Mapping[str, str] | None = None,
    ) -> str:
        self.published.append((topic, data, attributes))
        return f"msg-{len(self.published)}"


def _event(idx: int) -> StreamEvent:
    return StreamEvent(
        bucket="retikon-raw",
        name=f"raw/docs/sample-{idx}.txt",
        generation=str(idx),
        stream_id="stream-1",
        content_type="text/plain",
        size=12,
        device_id="device-1",
        site_id="site-1",
        modality="document",
    )


def test_stream_batcher_emits_on_size():
    batcher = StreamBatcher(max_batch_size=2, max_latency_s=60.0, max_backlog=10)
    assert batcher.add(_event(1), now=0.0) == []
    batch = batcher.add(_event(2), now=0.1)
    assert len(batch) == 2
    assert batcher.backlog == 0


def test_stream_batcher_emits_on_latency():
    batcher = StreamBatcher(max_batch_size=5, max_latency_s=1.0, max_backlog=10)
    assert batcher.add(_event(3), now=0.0) == []
    batch = batcher.flush(now=2.0)
    assert len(batch) == 1
    assert batcher.backlog == 0


def test_stream_batcher_backpressure():
    batcher = StreamBatcher(max_batch_size=5, max_latency_s=60.0, max_backlog=1)
    batcher.add(_event(4), now=0.0)
    with pytest.raises(StreamBackpressureError):
        batcher.add(_event(5), now=0.1)


def test_stream_pipeline_publishes_batch():
    publisher = FakePublisher()
    batcher = StreamBatcher(max_batch_size=2, max_latency_s=60.0, max_backlog=10)
    pipeline = StreamIngestPipeline(
        publisher=publisher,
        topic="projects/test/topics/stream-ingest",
        batcher=batcher,
    )

    result = pipeline.enqueue_events([_event(6), _event(7)], now=0.0)
    assert result.batch_published is True
    assert len(result.message_ids) == 1
    assert len(publisher.published) == 1

    _topic, data, _attrs = publisher.published[0]
    events = decode_stream_batch(data)
    assert len(events) == 2
    assert events[0].stream_id == "stream-1"


def test_stream_pipeline_flushes_on_latency():
    publisher = FakePublisher()
    batcher = StreamBatcher(max_batch_size=5, max_latency_s=1.0, max_backlog=10)
    pipeline = StreamIngestPipeline(
        publisher=publisher,
        topic="projects/test/topics/stream-ingest",
        batcher=batcher,
    )

    result = pipeline.enqueue_events([_event(8)], now=0.0)
    assert result.batch_published is False

    message_ids = pipeline.flush(now=2.0)
    assert len(message_ids) == 1
    assert len(publisher.published) == 1
