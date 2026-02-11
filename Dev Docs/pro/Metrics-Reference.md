# Retikon Metrics Reference (Ingest + Index)

This document defines the metrics emitted by ingestion pipelines and the
index builder. All values are ASCII, JSON-serializable, and stored in
Firestore (ingest) or the snapshot report JSON (index).

## Ingest Metrics (Firestore ingest doc `metrics`)

Top-level fields:

- `queue_wait_ms`: Time from GCS object creation to ingest start (ms).
- `wall_ms`: Wall time from ingest start to completion (ms).
- `queue_depth`: Inflight counts at ingest start (`inflight`, `inflight_total`).
- `system.cpu_user_s`: CPU user seconds consumed during ingest.
- `system.cpu_sys_s`: CPU system seconds consumed during ingest.
- `system.memory_peak_kb`: Peak resident set size during ingest (KB).
- `system.cold_start`: Best-effort cold-start flag.
- `system.instance_id`: Best-effort instance identifier (Cloud Run revision or hostname).
- `pipeline.timings_ms`: Stage timings (ms).
- `pipeline.stage_timings_ms`: Canonical stage timings (ms).
- `pipeline.pipe_ms`: Sum of canonical stage timings (ms).
- `pipeline.model_calls`: Model call counts and latency summaries.
- `pipeline.io`: Raw and derived bytes.
- `pipeline.quality`: Content quality counters (transcript, chunks, tokens).
- `pipeline.embeddings`: Embedding counts and vector dimensions.
- `pipeline.evidence`: Evidence counts by type.

### `pipeline.timings_ms` (ms)

Common keys:

- `probe`: Media probe time.
- `normalize`: Audio normalize time.
- `extract_text`: Document text extraction time.
- `ocr`: OCR time for PDFs.
- `chunk`: Document chunking time.
- `embed`: Document embedding time.
- `load_image`: Image decode and EXIF transpose.
- `image_embed`: Image embedding time (sum across frames).
- `extract_keyframes`: Video keyframe extraction time.
- `extract_audio`: Video audio extraction time.
- `audio_embed`: Audio embedding time.
- `transcribe`: Transcription time.
- `text_embed`: Text embedding time (transcript or doc chunks).
- `write_thumbnail`: Thumbnail write time (sum).
- `write_parquet`: Parquet write time (sum).
- `write_manifest`: Manifest write time.

### `pipeline.stage_timings_ms` (ms)

Canonical keys (always present, zero when unused):

- `download_ms`
- `decode_ms`
- `extract_audio_ms`
- `extract_frames_ms`
- `vad_ms`
- `transcribe_ms`
- `embed_text_ms`
- `embed_image_ms`
- `embed_audio_ms`
- `write_manifest_ms`
- `write_parquet_ms`
- `write_blobs_ms`
- `finalize_ms`

### `pipeline.model_calls`

Each entry is a summary:

- `calls`: Number of calls.
- `total_ms`: Sum of call times.
- `avg_ms`: Average call time.
- `max_ms`: Maximum call time.
- `min_ms`: Minimum call time.

Common call names:

- `image_embed`: Image embedding calls.
- `audio_embed`: Audio embedding calls.
- `text_embed`: Text embedding calls (doc or transcript).
- `transcribe`: Transcription calls.

### `pipeline.io`

- `bytes_raw`: Raw input bytes (from source object).
- `bytes_parquet`: Total parquet bytes written.
- `bytes_thumbnails`: Total thumbnail bytes written.
- `bytes_derived`: Total derived bytes (parquet + thumbnails).

### `pipeline.quality`

Document:

- `word_count`: Word count for extracted text.
- `token_count`: Total token count across chunks.
- `chunk_count`: Number of document chunks.

Audio/Video:

- `transcript_status`: `ok`, `no_speech`, `no_audio_track`, `skipped_too_long`,
  `skipped_by_policy`, or `failed`.
- `transcript_word_count`: Word count across transcript segments.
- `transcript_segment_count`: Number of transcript segments.
- `normalize_skipped`: Audio normalize skip flag.
- `audio_duration_ms`: Total audio duration (ms).
- `extracted_audio_duration_ms`: Extracted audio duration (ms).
- `trimmed_silence_ms`: Detected silence duration (ms).
- `transcribed_ms`: Transcribed duration (ms).
- `transcript_language`: Detected language (if available).
- `transcript_error_reason`: Error reason when `failed`.

Image:

- `width_px`: Image width.
- `height_px`: Image height.

### `pipeline.embeddings`

Per modality entry:

- `count`: Number of vectors written.
- `dims`: Vector dimension.

Keys:

- `text` (DocChunk or Transcript, dims 768)
- `image` (ImageAsset, dims 512)
- `audio` (AudioClip, dims 512)

### `pipeline.evidence`

- `frames`: Image/video frames (keyframes or single image).
- `snippets`: Document chunks.
- `segments`: Transcript segments (audio/video).

## Index Metrics (Snapshot report JSON)

The snapshot report is written alongside the DuckDB snapshot as
`<snapshot_uri>.json`.

New fields:

- `rows_added`: Sum of rows added in the build.
- `total_rows`: Total rows across indexed tables.
- `percent_changed`: Percentage of total rows that are new.
- `rows_added_by_table`: Map of table -> rows added.
- `snapshot_download_seconds`: Base snapshot download time (incremental).
- `snapshot_upload_seconds`: Snapshot upload time.
- `snapshot_report_upload_seconds`: Report upload time.
- `load_snapshot_seconds`: Time to download and attach base snapshot.
- `apply_deltas_seconds`: Time to apply new manifests into tables.
- `build_vectors_seconds`: Time to build HNSW indexes.
- `write_snapshot_seconds`: Time to checkpoint/flush the DB file.
- `upload_seconds`: Snapshot upload time (alias of `snapshot_upload_seconds`).
- `compaction_manifest_count`: Number of compaction manifests in scope.
- `latest_compaction_duration_seconds`: Duration of latest compaction.

Table mapping for `rows_added_by_table`:

- `doc_chunks` -> `DocChunk` core rows
- `transcripts` -> `Transcript` core rows
- `image_assets` -> `ImageAsset` core rows
- `audio_clips` -> `AudioClip` core rows
- `media_assets` -> `MediaAsset` core rows

Existing fields (still present):

- `tables`: Row counts per index table.
- `indexes`: Index sizes and metadata.
- `manifest_count`: Number of manifests used.
- `new_manifest_count`: Number of new manifests since last build.
- `manifest_fingerprint`: Hash of manifest set used.
