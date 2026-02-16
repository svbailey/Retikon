# Sprint 1 Test Matrix (Reranker + Search Contract v1)

This matrix defines the minimum test coverage required during Sprint 1.

## 1) Contract and validation tests

- Request validation
  - Reject unknown request fields.
  - Enforce `page_limit <= top_k` when both provided.
  - Enforce mode/modality precedence (`modalities` overrides `mode`).
- Typed error shape
  - Validate `error.code`, `error.message`, and `error.details[]`.
  - Cover at least `VALIDATION_ERROR`, `PAYLOAD_TOO_LARGE`,
    `UNSUPPORTED_MODE`.

Suggested files:
- `tests/pro/test_query_modes.py`
- `tests/core/test_query_service_core.py`

## 2) Pagination and grouping tests

- Deterministic cursor pagination
  - Same request + same snapshot marker -> same page sequence.
  - Tie-breakers include `primary_evidence_id`.
- Grouping output schema
  - `grouping.total_videos`
  - `grouping.total_moments`
  - `grouping.videos[].{asset_id, clip_count, best_score, top_moments[]}`

Suggested files:
- `tests/pro/test_query_modes.py`
- `tests/core/test_query_runner.py`

## 3) Reranker behavior tests

- Reranker enabled path on text-bearing candidates.
- Reranker skipped when no text-bearing candidates.
- Reranker timeout/failure fallback returns fused baseline results.
- `highlight_text` present for text-bearing moments.

Suggested files:
- `tests/core/test_query_runner.py`
- `tests/pro/test_query_modes.py`

## 4) Fusion + explainability tests

- Weighted RRF metadata present (`fusion_method`, `weight_version`).
- Missing-modality contributions are omitted (not worst-rank penalties).
- `why[]` includes modality contribution details.

Suggested files:
- `tests/core/test_query_runner.py`
- `tests/core/test_query_eval_metrics.py`

## 5) Regression/eval tests

- Golden pack run before/after Sprint 1 changes.
- Acceptance delta:
  - top-5 precision on text-bearing queries improves
  - no regression in deterministic metadata/OCR query cases

Artifacts:
- `tests/fixtures/eval/results-*.json`

## Exit criteria

- All new/updated tests pass in CI.
- Full suite passes locally (`pytest`).
- Sprint 1 acceptance criteria in `Dev Docs/pro/Sprint-Plan-v3.05.md` are
  satisfied and linked to test evidence.
