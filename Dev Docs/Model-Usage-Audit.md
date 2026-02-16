# Retikon Model Usage Audit (Code-Derived)

This document is derived from a code audit, not from existing docs. It
describes every model actually used in the codebase, how each model is
invoked, and where outputs are stored. Paths are included so future audits
can re-verify behavior.

Primary code paths reviewed:
- Embeddings and backends: `retikon_core/embeddings/`
- Ingestion pipelines: `retikon_core/ingestion/pipelines/`
- Transcription and OCR: `retikon_core/ingestion/transcribe.py`,
  `retikon_core/ingestion/ocr.py`
- Query runtime: `retikon_core/query_engine/query_runner.py`,
  `retikon_core/services/query_service_core.py`
- GraphAr schemas: `retikon_core/schemas/graphar/`
- Model download/export helpers: `scripts/download_models.py`,
  `scripts/export_onnx.py`, `scripts/quantize_onnx.py`
- Dev console label scoring: `gcp_adapter/dev_console_service.py`

## Model Inventory (Production Defaults)

| Model | Default name | Output dims | Used for | Code entry points |
| --- | --- | --- | --- | --- |
| Text embedding | `BAAI/bge-base-en-v1.5` | 768 | Doc chunk embeddings and transcript embeddings; text query embeddings | `retikon_core/embeddings/stub.py`, `retikon_core/ingestion/pipelines/document.py`, `retikon_core/ingestion/pipelines/audio.py`, `retikon_core/ingestion/pipelines/video.py`, `retikon_core/query_engine/query_runner.py` |
| Image embedding (CLIP image) | `openai/clip-vit-base-patch32` | 512 | Image embeddings for images and video keyframes; image query embeddings | `retikon_core/embeddings/stub.py`, `retikon_core/ingestion/pipelines/image.py`, `retikon_core/ingestion/pipelines/video.py`, `retikon_core/query_engine/query_runner.py` |
| Image text embedding (CLIP text) | `openai/clip-vit-base-patch32` | 512 | Text-to-image similarity (query text vs image vectors); label catalog embeddings | `retikon_core/embeddings/stub.py`, `retikon_core/query_engine/query_runner.py`, `gcp_adapter/dev_console_service.py` |
| Audio embedding (CLAP audio) | `laion/clap-htsat-fused` | 512 | Audio clip embeddings for audio and video | `retikon_core/embeddings/stub.py`, `retikon_core/ingestion/pipelines/audio.py`, `retikon_core/ingestion/pipelines/video.py` |
| Audio text embedding (CLAP text) | `laion/clap-htsat-fused` | 512 | Text-to-audio similarity (query text vs audio vectors) | `retikon_core/embeddings/stub.py`, `retikon_core/query_engine/query_runner.py` |
| Speech-to-text | `openai-whisper` family (default `small`) | N/A | Audio/video transcription into Transcript segments | `retikon_core/ingestion/transcribe.py`, `retikon_core/ingestion/pipelines/audio.py`, `retikon_core/ingestion/pipelines/video.py` |
| OCR | Tesseract via `pytesseract` | N/A | PDF/image OCR when enabled | `retikon_core/ingestion/ocr.py`, `retikon_core/ingestion/pipelines/document.py` |
| Stub embeddings | Deterministic stub (no model) | 768/512 | Dev/test embeddings when `USE_REAL_MODELS=0` or backend is `stub` | `retikon_core/embeddings/stub.py` |

## Embedding Backends and Model Selection

### Backend selection
Backends are resolved in `retikon_core/embeddings/stub.py`:
- `EMBEDDING_BACKEND` or `RETIKON_EMBEDDING_BACKEND` controls the default.
- Per-kind overrides: `TEXT_EMBED_BACKEND`, `IMAGE_EMBED_BACKEND`,
  `AUDIO_EMBED_BACKEND`, `IMAGE_TEXT_EMBED_BACKEND`,
  `AUDIO_TEXT_EMBED_BACKEND`.
- Supported values: `stub`, `hf`, `onnx`, `quantized`, `auto`.
  - `auto` means `hf` when `USE_REAL_MODELS=1`, otherwise `stub`.

### Real (HF) backends
`USE_REAL_MODELS=1` enables real model execution with Hugging Face stacks.
Key behavior (from `retikon_core/embeddings/stub.py`):
- Text: `sentence-transformers` `SentenceTransformer` model with L2
  normalization, plus `AutoTokenizer` for truncation to
  `TEXT_MODEL_MAX_TOKENS` (default 512) without special tokens.
- CLIP: `CLIPModel` + `CLIPProcessor` for image and text, embeddings are L2
  normalized.
- CLAP: `ClapModel` + `ClapProcessor` for audio and text, embeddings are L2
  normalized. Audio payloads are decoded with `soundfile`, averaged to mono,
  resampled to 48kHz if needed.

### ONNX backends
ONNX backends live in `retikon_core/embeddings/onnx_backend.py` and require
`onnxruntime`. Expected files:
- `MODEL_DIR/onnx/bge-text.onnx`
- `MODEL_DIR/onnx/clip-text.onnx`
- `MODEL_DIR/onnx/clip-image.onnx`
- `MODEL_DIR/onnx/clap-audio.onnx`
- `MODEL_DIR/onnx/clap-text.onnx`

ONNX embeddings are L2 normalized. Tokenization uses `AutoTokenizer` for BGE
and CLIP/CLAP processors for image/audio/text inputs.

### Quantized backends
Quantized backends use the same ONNX runtime path but prefer INT8 text models:
- `MODEL_DIR/onnx-quant/bge-text-int8.onnx`
- `MODEL_DIR/onnx-quant/clip-text-int8.onnx`

Per `retikon_core/embeddings/onnx_backend.py`, quantized image and CLAP models
use the non-quantized ONNX files (no separate INT8 assets are referenced).

### Stub embeddings
When `USE_REAL_MODELS=0` or backend is `stub`, deterministic vectors are
generated from SHA256 hashes of inputs. These vectors are not normalized and
exist only to keep pipelines working in dev/test.

## Ingestion-Time Model Usage

### Document ingestion
Code: `retikon_core/ingestion/pipelines/document.py`
- Text extraction:
  - PDF: `fitz` (PyMuPDF) `page.get_text()`
  - DOCX: `python-docx`
  - PPTX: `python-pptx`
  - CSV/TSV/XLSX: pandas table -> string rows
- OCR fallback:
  - If extracted text is empty and `ENABLE_OCR=1` and file is PDF, OCR runs
    via `ocr_text_from_pdf` (see OCR section).
- Chunking:
  - Uses `AutoTokenizer` for `TEXT_MODEL_NAME` with
    `return_offsets_mapping=True` and `add_special_tokens=False`.
  - Falls back to a whitespace tokenizer when `RETIKON_TOKENIZER` is set to
    `stub|simple|whitespace` or when `transformers` is missing.
  - Chunk size and overlap come from `CHUNK_TARGET_TOKENS` and
    `CHUNK_OVERLAP_TOKENS` (required in `Config`).
  - Each chunk records `char_start`, `char_end`, `token_start`, `token_end`,
    and `token_count`.
- Embeddings:
  - `get_text_embedder(768)` produces one vector per chunk.
  - Batch size from `TEXT_EMBED_BATCH_SIZE` (or `DOC_EMBED_BATCH_SIZE`).
  - Model name recorded in GraphAr as `embedding_model=TEXT_MODEL_NAME`.

### Image ingestion
Code: `retikon_core/ingestion/pipelines/image.py`
- Image loading: PIL, with EXIF transpose, converted to RGB.
- Preprocessing: optional resize via `IMAGE_EMBED_MAX_DIM` using LANCZOS.
- Embeddings:
  - `get_image_embedder(512)` produces CLIP image embeddings.
  - Batch size from `IMAGE_EMBED_BATCH_SIZE`.
  - Model name recorded as `embedding_model=IMAGE_MODEL_NAME`.
- Thumbnails:
  - Stored under `thumbnails/<media_asset_id>/image.jpg` when configured.

### Audio ingestion
Code: `retikon_core/ingestion/pipelines/audio.py`
- Audio normalization: ffmpeg to mono 48kHz WAV unless
  `AUDIO_SKIP_NORMALIZE_IF_WAV=1` and input already matches.
- Audio embeddings:
  - `get_audio_embedder(512)` on the audio bytes (CLAP audio).
- Transcription:
  - Runs only if `AUDIO_TRANSCRIBE=1` and `TRANSCRIBE_ENABLED=1` and tier is
    not `off`.
  - Uses VAD (`analyze_audio`) when enabled to avoid transcription on silence.
  - Transcribe policy can cap duration (`TRANSCRIBE_MAX_MS` and org/plan
    overrides).
  - `transcribe_audio` uses Whisper when `USE_REAL_MODELS=1`, stub otherwise.
- Transcript embeddings:
  - Each Whisper segment is embedded via `get_text_embedder(768)`.
  - Model name recorded as `embedding_model=TEXT_MODEL_NAME`.

### Video ingestion
Code: `retikon_core/ingestion/pipelines/video.py`
- Keyframes:
  - Extracted with ffmpeg scene detection or FPS fallback.
  - Each keyframe embedded via `get_image_embedder(512)` (CLIP image).
  - Optional resize via `VIDEO_EMBED_MAX_DIM`.
- Audio:
  - Audio extracted via ffmpeg to mono 48kHz WAV.
  - `get_audio_embedder(512)` produces the CLAP audio vector for the clip.
- Transcription:
  - Same gating/policy logic as audio ingestion.
  - Transcript segments embedded via `get_text_embedder(768)`.

## Query-Time Model Usage

Code: `retikon_core/query_engine/query_runner.py`,
`retikon_core/services/query_service_core.py`

### Text queries
When `search_type=vector` and `query_text` is provided:
- Documents and transcripts:
  - BGE text embeddings via `get_text_embedder(768)`.
- Images:
  - CLIP text embeddings via `get_image_text_embedder(512)`.
- Audio:
  - CLAP text embeddings via `get_audio_text_embedder(512)`.
- Embeddings are cached per text query (LRU size 256).
- Similarity uses cosine distance in DuckDB and score is
  `score = clamp(1.0 - cosine_distance, 0.0, 1.0)`.
- `mode` or `modalities` can skip unused embeddings (e.g., `mode=text` skips
  image/audio text embeddings).

### Image queries
When `image_base64` is provided:
- Image bytes are decoded to PIL image.
- `get_image_embedder(512)` computes CLIP image embedding.
- Compared against stored `ImageAsset.clip_vector`.

### Warmup
Query service optionally warms models at startup:
- `warm_query_models` runs embeddings for text, image_text, audio_text, and
  image using dummy inputs (see `query_service_core.py`).

## OCR Details

Code: `retikon_core/ingestion/ocr.py`
- Local OCR uses `pytesseract` + `tesseract` binary.
- PDF OCR:
  - PyMuPDF renders pages to images, then OCRs each page.
  - Controlled by `OCR_MAX_PAGES`.
- External OCR connectors:
  - Connector definitions stored at `control/ocr_connectors.json`.
  - Selection logic uses `OCR_CONNECTOR_ID`, or the single enabled/default
    connector.
  - Requests include `content_base64`, `content_type`, and `max_pages`.
  - Auth can be `bearer` or custom header with token from env var.

## Dev Console Visual Labels

Code: `gcp_adapter/dev_console_service.py`
- Label catalog from `retikon_core/labels/label_catalog.csv` (or
  `LABEL_CATALOG_PATH` override).
- Label embeddings are computed once per backend via
  `get_image_text_embedder(512)` (CLIP text).
- Scores are dot products between label embeddings and stored image vectors
  (CLIP image), then clamped to `[0.0, 1.0]`.

## Storage and Indexing

Vector storage (GraphAr schemas):
- `DocChunk.text_vector` (768) in `retikon_core/schemas/graphar/DocChunk/prefix.yml`
- `Transcript.text_embedding` (768) in `retikon_core/schemas/graphar/Transcript/prefix.yml`
- `ImageAsset.clip_vector` (512) in `retikon_core/schemas/graphar/ImageAsset/prefix.yml`
- `AudioClip.clap_embedding` (512) in `retikon_core/schemas/graphar/AudioClip/prefix.yml`

Indexing (DuckDB vss, HNSW):
- Indexes are built for the four vector columns in
  `retikon_core/query_engine/index_builder.py`.
- HNSW params from `HNSW_EF_CONSTRUCTION` and `HNSW_M`.

## Model Download and Export

Code: `scripts/download_models.py`, `scripts/export_onnx.py`,
`scripts/quantize_onnx.py`
- `scripts/download_models.py` downloads:
  - BGE, CLIP, CLAP, and Whisper into `MODEL_DIR`.
  - Exports ONNX if `EXPORT_ONNX=1` or if any backend is `onnx|quantized`.
  - Quantizes ONNX if `QUANTIZE_ONNX=1` or any backend is `quantized`.
- ONNX exports use normalized embedding outputs for all encoders.

## Audit Notes (Code-Accurate Behaviors)

- GraphAr `embedding_model` fields are populated with the model name env vars
  (`TEXT_MODEL_NAME`, `IMAGE_MODEL_NAME`, `AUDIO_MODEL_NAME`) regardless of
  whether the backend is `stub`, `onnx`, or `quantized`.
- Quantized backends reference INT8 ONNX files only for BGE text and CLIP
  text. CLIP image and CLAP audio/text reuse the standard ONNX files.
- When `USE_REAL_MODELS=0`, Whisper transcription returns a single empty
  segment covering the full duration; transcript embeddings are therefore
  skipped unless real models are enabled.
