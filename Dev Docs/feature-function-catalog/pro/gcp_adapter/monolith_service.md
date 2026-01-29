# gcp_adapter/monolith_service.py

Edition: Pro

## Functions
- `_optional_stream_ingest`: Internal helper that loads stream ingest if configured, so monolith startup is resilient.
- `_attach_routes`: Internal helper that attaches routes, so the monolith reuses existing service endpoints.
- `lifespan`: Function that runs startup/shutdown hooks, so query/audit warmups and stream ingest flush run.
- `health`: Reports service health, so the monolith can be monitored.

## Classes
- `HealthResponse`: Data structure or helper class for Health Response, so health endpoints are consistent.
