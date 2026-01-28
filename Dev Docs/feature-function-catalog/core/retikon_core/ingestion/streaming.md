# retikon_core/ingestion/streaming.py

Edition: Core

## Functions
- `stream_event_to_dict`: Function that streams event to dict, so content can be safely ingested and processed.
- `stream_event_from_dict`: Function that streams event from dict, so content can be safely ingested and processed.
- `decode_stream_batch`: Function that decode stream batch, so content can be safely ingested and processed.
- `_coerce_int`: Internal helper that converts int, so content can be safely ingested and processed.

## Classes
- `StreamEvent`: Data structure or helper class for Stream Event, so content can be safely ingested and processed.
  - Methods
    - `to_gcs_event`: Function that converts to GCS event, so content can be safely ingested and processed.
- `StreamDispatchResult`: Data structure or helper class for Stream Dispatch Result, so content can be safely ingested and processed.
- `StreamBackpressureError`: Data structure or helper class for Stream Backpressure Error, so content can be safely ingested and processed.
- `StreamBatcher`: Data structure or helper class for Stream Batcher, so content can be safely ingested and processed.
  - Methods
    - `__init__`: Sets up the object, so content can be safely ingested and processed.
    - `backlog`: Function that backlog, so content can be safely ingested and processed.
    - `can_accept`: Function that checks whether it can accept, so content can be safely ingested and processed.
    - `add`: Function that add, so content can be safely ingested and processed.
    - `flush`: Function that flushes it, so content can be safely ingested and processed.
    - `_maybe_flush`: Internal helper that maybe flush, so content can be safely ingested and processed.
    - `_drain`: Internal helper that drain, so content can be safely ingested and processed.
- `StreamIngestPipeline`: Data structure or helper class for Stream Ingest Pipeline, so content can be safely ingested and processed.
  - Methods
    - `__init__`: Sets up the object, so content can be safely ingested and processed.
    - `enqueue`: Function that enqueue, so content can be safely ingested and processed.
    - `enqueue_events`: Function that enqueue events, so content can be safely ingested and processed.
    - `flush`: Function that flushes it, so content can be safely ingested and processed.
    - `_publish_batch`: Internal helper that sends batch, so content can be safely ingested and processed.
