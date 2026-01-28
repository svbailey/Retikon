# retikon_core/edge/policies.py

Edition: Core

## Classes
- `AdaptiveBatchPolicy`: Data structure or helper class for Adaptive Batch Policy, so edge ingestion is resilient.
  - Methods
    - `tune`: Function that tunes it, so edge ingestion is resilient.
- `BackpressurePolicy`: Data structure or helper class for Backpressure Policy, so edge ingestion is resilient.
  - Methods
    - `should_accept`: Function that decides whether it should accept, so edge ingestion is resilient.
