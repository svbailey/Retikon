# retikon_core/ingestion/idempotency.py

Edition: Core

## Functions
- `build_doc_id`: Function that builds doc ID, so content can be safely ingested and processed.

## Classes
- `IdempotencyDecision`: Data structure or helper class for Idempotency Decision, so content can be safely ingested and processed.
- `InMemoryIdempotency`: Data structure or helper class for In Memory Idempotency, so content can be safely ingested and processed.
  - Methods
    - `__init__`: Sets up the object, so content can be safely ingested and processed.
    - `begin`: Function that begin, so content can be safely ingested and processed.
    - `mark_completed`: Function that marks completed, so content can be safely ingested and processed.
    - `mark_failed`: Function that marks failed, so content can be safely ingested and processed.
    - `mark_dlq`: Function that marks DLQ, so content can be safely ingested and processed.
