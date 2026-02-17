# Retrieval Eval Set (Staging)

This eval set targets the staging graph built from unique eval assets.

## Current baseline run

- run_id: `sprint4-eval-20260217-172337`
- bucket: `retikon-raw-simitor-staging`
- prefix: `raw_clean`
- latest eval run: `sprint4-staging-20260217-191730` (2026-02-17)
- newest eval run: `sprint4-staging-20260217-191730`
- latest results file: `tests/fixtures/eval/results-sprint4-staging-20260217-191730.json`
- latest overall metrics: `recall@10=1.0`, `recall@50=1.0`, `MRR@10=0.8333`, `top_k_overlap=1.0`

Queries live in:
- `tests/fixtures/eval/golden_queries.json` (preferred golden pack)
- `tests/fixtures/eval/queries.jsonl` (line-delimited format)

Both reference ingested URIs from the run above.

## Regenerate the eval set

1) Generate a unique eval asset set and queries:
```
RUN_ID="eval-$(date +%Y%m%d-%H%M%S)"
python scripts/gen_eval_assets.py --run-id "$RUN_ID"
```

Prereqs: `pip install pillow` and `ffmpeg` available on PATH for image/video assets.

2) Ingest the generated assets:
```
python scripts/load_test_ingest.py --project simitor --bucket retikon-raw-simitor-staging \
  --prefix raw_clean --source "tests/fixtures/eval/assets/$RUN_ID" \
  --count 7 --run-id "$RUN_ID" --poll
```

3) Rebuild the index snapshot before running evals:
```
gcloud run jobs execute retikon-index-builder-staging --region us-central1 --project simitor --wait
```

4) Run retrieval eval against staging:
```
python scripts/run_retrieval_eval.py \
  --query-url "https://<query-service>/query" \
  --auth-token "$RETIKON_AUTH_TOKEN" \
  --eval-file tests/fixtures/eval/golden_queries.json \
  --output tests/fixtures/eval/results-$(date +%Y%m%d-%H%M%S).json
```

## Notes

- Docs use vector queries derived from unique text content.
- Images use image queries (`image_path`).
- Audio/video use metadata queries for deterministic matches.
- Eval output includes MRR, recall, per-modality latency, and top-k overlap.
