# retikon_core/ingestion/idempotency_sqlite.py

Edition: Core

## Classes
- `SqliteIdempotency`: Data structure or helper class for Sqlite Idempotency, so content can be safely ingested and processed.
  - Methods
    - `__post_init__`: Internal helper that post init  , so content can be safely ingested and processed.
    - `_connect`: Internal helper that connect, so content can be safely ingested and processed.
    - `_init_db`: Internal helper that init db, so content can be safely ingested and processed.
    - `begin`: Function that begin, so content can be safely ingested and processed.
    - `mark_completed`: Function that marks completed, so content can be safely ingested and processed.
    - `mark_failed`: Function that marks failed, so content can be safely ingested and processed.
    - `mark_dlq`: Function that marks DLQ, so content can be safely ingested and processed.
