# Retrieval Eval Set (Staging)

This eval set targets the staging graph built from unique eval assets.

## Current baseline run

- run_id: `eval-20260214-164126`
- bucket: `retikon-raw-simitor-staging`
- prefix: `raw_clean`
- latest eval run: `eval-20260216-110825`
- newest eval run: `eval-20260216-110825`

Queries live in `tests/fixtures/eval/queries.jsonl` and reference the ingested
URIs from the run above.

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

## Notes

- Docs use vector queries derived from unique text content.
- Images use image queries (`image_path`).
- Audio/video use metadata queries for deterministic matches.
