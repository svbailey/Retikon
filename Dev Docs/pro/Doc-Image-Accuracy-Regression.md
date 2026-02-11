# Doc/Image Accuracy Regression Suite (Staging)

Purpose: guard doc/image accuracy while optimizing latency and cost. This suite
checks basic extraction/embedding quality at ingest time and is required before
any speed-focused changes roll out.

## Asset set (staging bucket)

Use a fixed run id and keep assets stable. Suggested staging assets:

Docs:
- `gs://retikon-raw-simitor-staging/raw_clean/docs/<run-id>/doc-minimal.pdf`
- `gs://retikon-raw-simitor-staging/raw_clean/docs/<run-id>/doc-typical.pdf`
- `gs://retikon-raw-simitor-staging/raw_clean/docs/<run-id>/doc-multipage.pdf`

Images:
- `gs://retikon-raw-simitor-staging/raw_clean/images/<run-id>/img-256.jpg`
- `gs://retikon-raw-simitor-staging/raw_clean/images/<run-id>/img-1024.jpg`
- `gs://retikon-raw-simitor-staging/raw_clean/images/<run-id>/img-large.jpg`

If you do not have these assets yet, upload small fixtures from `tests/fixtures`
first, then replace with real samples as soon as available.

## Quality expectations (ingest metrics)

Docs (per asset):
- `pipeline.quality.word_count` >= 5 (minimal), >= 50 (typical), >= 200 (multi-page)
- `pipeline.quality.chunk_count` >= 1 (minimal), >= 3 (typical), >= 8 (multi-page)
- `pipeline.embeddings.text.count` >= `chunk_count`

Images (per asset):
- `pipeline.quality.width_px` >= 64 (minimal), >= 256 (standard), >= 1024 (large)
- `pipeline.quality.height_px` >= 64 (minimal), >= 256 (standard), >= 1024 (large)
- `pipeline.embeddings.image.count` >= 1

## How to run

1) Ingest assets (staging):

```bash
python scripts/load_test_ingest.py \
  --source tests/fixtures \
  --count 3 \
  --poll
```

2) Capture run id from the ingest tool output.

3) Validate metrics:

```bash
python scripts/report_ingest_baseline.py \
  --project simitor \
  --bucket retikon-raw-simitor-staging \
  --raw-prefix raw_clean \
  --run-id <run-id> \
  --quality-check
```

## Pass/Fail

- Fail if any doc has zero text/zero chunks or if embeddings < chunks.
- Fail if any image has zero dimensions or missing image embeddings.
- If failures occur, inspect `pipeline.timings_ms` and `pipeline.quality` for
  regressions before proceeding with performance work.
