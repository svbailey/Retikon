# Retikon 2.5 Release Notes

Status: Final
Owner: Eng
Date: 2026-01-27

## Summary

Retikon 2.5 finalizes the compliance fixes required by the 2.5 build kit,
adds query‑side performance mitigations (modality filtering + warmup), and
records new load‑test baselines. The release is production‑ready and remains
backwards compatible with existing 2.5 clients.

## Highlights

- UUIDv4 enforced across all pipeline IDs.
- Tokenizer chunking uses Hugging Face `AutoTokenizer` with `offset_mapping`.
- Content‑type + extension validation enforced at ingest.
- `.doc` and `.ppt` removed from Core allowlist (legacy formats no longer accepted).
- Query API supports optional `mode` / `modalities` to skip unused embeddings.
- Query service warms embeddings on startup to reduce cold‑start latency.
- Slow query timing logs remain enabled for tail‑latency visibility.
- Load‑test baselines updated for text‑only vs multimodal queries.

## API and Behavior Changes

### Query API

New optional fields:
- `mode`: `text`, `image`, `audio`, `all` (mutually exclusive with `modalities`).
- `modalities`: list of `document`, `transcript`, `image`, `audio`.

Notes:
- Default behavior remains unchanged (all modalities).
- `image_base64` requires `image` modality or `mode=image|all`.
- Text queries can now skip image/audio embedding work by using `mode=text`.

### Ingestion / Pipelines

- UUIDv4 used everywhere for vertex/edge IDs.
- Content‑type and extension must both match allowlists.
- Legacy `.doc` / `.ppt` are rejected in Core.
- Tokenization stores `char_start` / `char_end` using tokenizer offsets.

### OCR (Optional)

- OCR is optional and **off by default** (`ENABLE_OCR=0`).
- OCR dependencies are optional and should only be installed for OCR use cases.
- If enabled, OCR respects `OCR_MAX_PAGES` for PDFs/images.

## Configuration Additions

Query service:
- `QUERY_WARMUP` (default `1`) to enable warmup embeds on startup.
- `QUERY_WARMUP_TEXT` (default `retikon warmup`) text used for warmup.
- `SLOW_QUERY_MS` and `LOG_QUERY_TIMINGS` retained for tail‑latency logging.

## Load‑Testing Baselines

Recorded in `Dev Docs/Load-Testing.md` (2026‑01‑27):
- Text‑only (`mode=text`) baseline.
- Default multimodal baseline.

## Documentation Updates

- `Dev Docs/Retikon-GCP-Build-Kit-v2.5.md`
  - Optional OCR and query warmup details.
  - Index builder alignment behavior documented.
- `Dev Docs/Load-Testing.md`
  - Updated query baselines (text‑only vs multimodal).

## Backwards Compatibility

- Existing clients remain compatible.
- New query parameters are optional.
- No schema prefix change (still `retikon_v2/`).

## Known Limitations

- OCR is optional; Core does not perform OCR unless explicitly enabled.
- Legacy `.doc` / `.ppt` inputs are not supported in Core.

## Checklist Status

All 2.5 compliance items are complete and tests are green. 2.5 is ready
for production use.
