# retikon_core/redaction/media.py

Edition: Core

## Functions
- `media_redaction_enabled`: Helper that checks if media redaction is enabled, so hooks remain opt-in.
- `resolve_media_types`: Function that resolves media redaction types, so policies map to supported types.
- `plan_media_redaction`: Function that builds a redaction plan stub, so pipelines can wire in later.
- `redact_media_payload`: Function that returns payload + plan, so hooks stay no-op by default.

## Classes
- `RedactionRegion`: Data structure for a redaction region, so stubs can express targets.
- `RedactionOperation`: Data structure for a redaction operation, so stubs can be expanded later.
- `RedactionPlan`: Data structure for a redaction plan, so pipelines can record intent.
