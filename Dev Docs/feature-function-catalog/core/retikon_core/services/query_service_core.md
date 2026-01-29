# retikon_core/services/query_service_core.py

Edition: Core

## Functions
- `resolve_modalities`: Validates and resolves modalities, so query inputs are consistent.
- `resolve_search_type`: Validates search type, so query inputs are consistent.
- `validate_query_payload`: Validates query payload, so invalid requests are rejected early.
- `run_query`: Executes query logic, so results are consistent across local and Pro.
- `apply_privacy_redaction`: Redacts snippets, so privacy policies are enforced.
- `describe_query_modality`: Summarizes query modality, so logging and metering are consistent.
- `build_query_response`: Builds response payload, so adapters stay thin.
- `warm_query_models`: Warms models, so tail latency is reduced.

## Classes
- `QueryValidationError`: Validation error wrapper, so adapters can return clear HTTP responses.
- `QueryRequest`: Request schema for query endpoints, so inputs are consistent.
- `QueryHit`: Response item schema for query endpoints, so outputs are consistent.
- `QueryResponse`: Response schema for query endpoints, so outputs are consistent.
