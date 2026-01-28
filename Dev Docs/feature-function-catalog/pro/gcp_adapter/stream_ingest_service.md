# gcp_adapter/stream_ingest_service.py

Edition: Pro

## Functions
- `_correlation_id`: Internal helper that correlation ID, so streaming ingestion is reliable.
- `add_correlation_id`: Function that add correlation ID, so streaming ingestion is reliable.
- `_stream_topic`: Internal helper that streams topic, so streaming ingestion is reliable.
- `_batch_max`: Internal helper that batch max, so streaming ingestion is reliable.
- `_batch_latency_ms`: Internal helper that batch latency ms, so streaming ingestion is reliable.
- `_backlog_max`: Internal helper that backlog max, so streaming ingestion is reliable.
- `_flush_interval_s`: Internal helper that flushes interval s, so streaming ingestion is reliable.
- `_init_pipeline`: Internal helper that init pipeline, so streaming ingestion is reliable.
- `_flush_loop`: Internal helper that flushes loop, so streaming ingestion is reliable.
- `_start_flush_loop`: Internal helper that start flush loop, so streaming ingestion is reliable.
- `_stop_flush_loop`: Internal helper that stop flush loop, so streaming ingestion is reliable.
- `health`: Reports service health, so streaming ingestion is reliable.
- `stream_status`: Function that streams status, so streaming ingestion is reliable.
- `ingest_stream`: Function that ingests stream, so streaming ingestion is reliable.
- `ingest_stream_push`: Function that ingests stream push, so streaming ingestion is reliable.
- `_parse_stream_events`: Internal helper that parses stream events, so streaming ingestion is reliable.
- `_get_dlq_publisher`: Internal helper that gets DLQ publisher, so streaming ingestion is reliable.
- `_publish_dlq`: Internal helper that sends DLQ, so streaming ingestion is reliable.

## Classes
- `HealthResponse`: Data structure or helper class for Health Response, so streaming ingestion is reliable.
- `StreamIngestResponse`: Data structure or helper class for Stream Ingest Response, so streaming ingestion is reliable.
- `StreamStatusResponse`: Data structure or helper class for Stream Status Response, so streaming ingestion is reliable.
