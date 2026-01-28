# gcp_adapter/idempotency_firestore.py

Edition: Pro

## Classes
- `FirestoreIdempotency`: Data structure or helper class for Firestore Idempotency, so idempotency is enforced with Firestore.
  - Methods
    - `begin`: Function that begin, so idempotency is enforced with Firestore.
    - `mark_completed`: Function that marks completed, so idempotency is enforced with Firestore.
    - `mark_failed`: Function that marks failed, so idempotency is enforced with Firestore.
    - `mark_dlq`: Function that marks DLQ, so idempotency is enforced with Firestore.
