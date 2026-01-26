# Retikon Multimodal RAG Platform - GCP Build Kit v2.5 Update

This document is the development reference for the Retikon v2.5 GCP build kit.
It describes the repository layout, cloud infrastructure, container build, and
application logic for multimodal ingestion and retrieval across text, images,
audio, and video.

## Project Repository Structure

The repository is split into two top-level modules to separate cloud-agnostic
core logic from GCP-specific entry points.

```
retikon-project/
  retikon_core/
    ingestion/
      pipelines/
        video.py
        audio.py
        image.py
        document.py
    query_engine/
      query_runner.py
      index_builder.py
    __init__.py
  gcp_adapter/
    ingestion_service.py
    query_service.py
    __init__.py
  infrastructure/
    terraform/
      main.tf
      variables.tf
      outputs.tf
    README.md
  Dockerfile
  requirements.txt
```

### Module Responsibilities

- `retikon_core/` contains cloud-agnostic ingestion pipelines and the query
  engine. It owns the data model, pipeline logic, embeddings, and query
  execution.
- `gcp_adapter/` contains minimal Flask or FastAPI entry points for Cloud Run.
  It parses HTTP requests and delegates to `retikon_core` functions.
- `infrastructure/terraform/` defines all GCP resources used by the deployment.

This structure replaces the old monolithic `backend/` layout and provides a
clear separation of concerns.

## Infrastructure: GCP Services and Terraform

All infrastructure is defined in Terraform. The deployment uses Cloud Run
services for ingestion and query, Cloud Run Jobs for offline index building,
GCS buckets for storage, Artifact Registry for container images, and Eventarc
for ingestion triggers.

### Storage Buckets

Two buckets are used: one for raw uploads and one for graph data.

```hcl
resource "google_storage_bucket" "raw_ingest_bucket" {
  name          = "retikon_raw_ingest_${var.env}"
  location      = var.region
  force_destroy = true
}

resource "google_storage_bucket" "graph_data_bucket" {
  name          = "retikon_graph_data_${var.env}"
  location      = var.region
  force_destroy = true
}
```

These buckets are the GCP equivalents of the S3 buckets used in the v2 stack.
Raw files live under a `raw/` prefix, while graph data is stored under a
`retikon_v2/` prefix.

### Artifact Registry

The container image (with models pre-packaged) is built and pushed to Artifact
Registry.

```hcl
resource "google_artifact_registry_repository" "container_repo" {
  name     = "retikon-repo"
  format   = "DOCKER"
  location = var.region
}
# Image tag example:
# $REGION-docker.pkg.dev/$PROJECT/retikon-repo/retikon-image:latest
```

### Service Accounts and Permissions

Cloud Run services run under dedicated service accounts with minimal IAM
permissions.

```hcl
resource "google_service_account" "ingestion_sa" {
  account_id   = "retikon-ingest-sa-${var.env}"
  display_name = "Retikon Ingestion Service Account"
}

resource "google_service_account" "query_sa" {
  account_id   = "retikon-query-sa-${var.env}"
  display_name = "Retikon Query Service Account"
}

resource "google_storage_bucket_iam_member" "ingest_raw_access" {
  bucket = google_storage_bucket.raw_ingest_bucket.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.ingestion_sa.email}"
}

resource "google_storage_bucket_iam_member" "ingest_graph_access" {
  bucket = google_storage_bucket.graph_data_bucket.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.ingestion_sa.email}"
}

resource "google_storage_bucket_iam_member" "query_graph_access" {
  bucket = google_storage_bucket.graph_data_bucket.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.query_sa.email}"
}
```

### Cloud Run Services (Ingestion and Query)

Two Cloud Run services are deployed from the same image with different
entrypoints.

```hcl
resource "google_cloud_run_service" "ingestion_service" {
  name     = "retikon-ingestion-${var.env}"
  location = var.region

  template {
    spec {
      serviceAccountName = google_service_account.ingestion_sa.email
      containers {
        image = "${google_artifact_registry_repository.container_repo.repository_url}/retikon-image:latest"
        command = ["gunicorn"]
        args    = ["-b", "0.0.0.0:8080", "gcp_adapter.ingestion_service:app"]
        resources { limits = { memory = "4Gi" } }
        env = [
          { name = "GRAPH_BUCKET", value = google_storage_bucket.graph_data_bucket.name }
        ]
      }
    }
  }

  ingress_type = "internal"
}

resource "google_cloud_run_service" "query_service" {
  name     = "retikon-query-${var.env}"
  location = var.region

  template {
    spec {
      serviceAccountName = google_service_account.query_sa.email
      containers {
        image = "${google_artifact_registry_repository.container_repo.repository_url}/retikon-image:latest"
        command = ["gunicorn"]
        args    = ["-b", "0.0.0.0:8080", "gcp_adapter.query_service:app"]
        resources { limits = { memory = "2Gi" } }
        env = [
          { name = "GRAPH_BUCKET", value = google_storage_bucket.graph_data_bucket.name }
        ]
      }
    }
  }

  ingress_type = "all"
  autogenerate_revision_name = true
}
```

The ingestion service is internal and invoked by Eventarc. The query service is
internet-facing.

### Cloud Run Job (Index Builder)

An optional Cloud Run Job can build or refresh indexes.

```hcl
resource "google_cloud_run_v2_job" "index_builder" {
  name         = "retikon-index-builder-${var.env}"
  location     = var.region
  launch_stage = "GA"

  template {
    template {
      containers {
        image = "${google_artifact_registry_repository.container_repo.repository_url}/retikon-image:latest"
        command = ["python"]
        args    = ["-m", "retikon_core.query_engine.index_builder"]
        serviceAccountName = google_service_account.query_sa.email
        env = [
          { name = "GRAPH_BUCKET", value = google_storage_bucket.graph_data_bucket.name }
        ]
        resources { limits = { memory = "2Gi" } }
      }
      max_retries = 0
      timeout     = "900s"
    }
  }
}
```

### Eventarc Trigger for GCS Ingestion

Eventarc triggers ingestion when a new object is finalized in the raw bucket.

```hcl
resource "google_eventarc_trigger" "gcs_ingest_trigger" {
  name     = "retikon-ingest-trigger-${var.env}"
  location = var.region

  event_filters {
    attribute = "type"
    value     = "google.cloud.storage.object.v1.finalized"
  }

  event_filters {
    attribute = "bucket"
    value     = google_storage_bucket.raw_ingest_bucket.name
  }

  destination {
    cloud_run_service {
      service = google_cloud_run_service.ingestion_service.name
      region  = var.region
      path    = "/ingest"
    }
  }

  service_account = google_service_account.ingestion_sa.email
}
```

## Dockerfile: Container with Preloaded Models

The container includes dependencies and preloaded model weights to minimize
cold-start time.

```dockerfile
FROM python:3.10-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils ffmpeg libsndfile1 git && \
    rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Application code
COPY retikon_core/ /app/retikon_core/
COPY gcp_adapter/ /app/gcp_adapter/

# Optional: download model weights at build time into /app/models/

ENV PYTHONPATH=/app
WORKDIR /app

# Default entrypoint for Query service
CMD ["gunicorn", "-b", "0.0.0.0:8080", "gcp_adapter.query_service:app"]
```

Required packages include `torch`, `torchaudio`, `transformers`,
`laion-clap==1.1.7`, `openai-whisper`, `decord==0.6.0`, `Pillow`, `pandas`,
`python-docx`, and `python-pptx`.

## Ingestion Pipelines (retikon_core.ingestion.pipelines)

### Video Pipeline (video.py)

- Enforces a hard 300-second duration cap. Videos longer than 5 minutes are
  skipped to avoid timeouts.
- Extracts keyframes and embeds them with CLIP.
- Extracts audio, transcribes with Whisper, and embeds with CLAP.
- Writes MediaAsset, ImageAsset, Transcript, and AudioClip vertices to GraphAr
  Parquet in GCS.

```python
import decord
import math
import os
import uuid
from PIL import Image

from . import audio as audio_pipeline
from . import image as image_pipeline

def ingest_video(bucket: str, key: str):
    tmp_path = f"/tmp/{uuid.uuid4()}.mp4"
    gcs_client.download_file(bucket, key, tmp_path)

    vr = decord.VideoReader(tmp_path)
    num_frames = len(vr)
    fps = vr.get_avg_fps() or 1.0
    duration_seconds = num_frames / fps
    if duration_seconds > 300:
        print(f"Video too long ({duration_seconds:.1f}s > 300s). Skipping.")
        return

    interval = int(fps) or 1
    frame_indices = list(range(0, num_frames, interval))
    frames = vr.get_batch(frame_indices)

    image_pipeline._load_clip_model()
    frame_vectors = []
    for frame in frames:
        img = Image.fromarray(frame.asnumpy(), mode="RGB")
        inputs = image_pipeline.clip_preprocess(images=img, return_tensors="pt")
        inputs = inputs.to(image_pipeline.clip_device)
        with torch.no_grad():
            emb = image_pipeline.clip_model.get_image_features(**inputs)
        frame_vectors.append(emb.squeeze().tolist())

    audio_pipeline._load_audio_models()
    transcript_segments = audio_pipeline._whisper_transcribe(tmp_path)
    audio_emb = audio_pipeline.clap_model.get_audio_embedding(
        *audio_pipeline.load_audio(tmp_path)
    )
    audio_vector = audio_emb.squeeze().tolist()

    # Build MediaAsset, ImageAsset, Transcript, and AudioClip records.
    # Write GraphAr Parquet files to GCS.
```

### Audio Pipeline (audio.py)

- Transcribes audio with Whisper.
- Embeds audio with CLAP for audio similarity search.
- Stores Transcript segments and a single AudioClip embedding per file.

```python
import torchaudio
import uuid

from . import _load_models

def ingest_audio(bucket: str, key: str):
    tmp_path = f"/tmp/{uuid.uuid4()}.wav"
    gcs_client.download_file(bucket, key, tmp_path)

    _load_models()
    segments = whisper_model.transcribe(tmp_path)["segments"]
    transcript_segments = [(s["start"], s["end"], s["text"]) for s in segments]

    waveform, sample_rate = torchaudio.load(tmp_path)
    if sample_rate != 48000:
        waveform = torchaudio.functional.resample(waveform, sample_rate, 48000)
        sample_rate = 48000

    audio_emb = clap_model.get_audio_embedding(waveform, sample_rate)
    audio_vector = audio_emb.squeeze().tolist()

    # Build MediaAsset, Transcript, and AudioClip records.
    # Write GraphAr Parquet files to GCS.
```

### Image Pipeline (image.py)

- Generates CLIP image embeddings and stores an ImageAsset vertex.

```python
from PIL import Image
import torch
import uuid

def ingest_image(bucket: str, key: str):
    tmp_path = f"/tmp/{uuid.uuid4()}"
    gcs_client.download_file(bucket, key, tmp_path)

    img = Image.open(tmp_path).convert("RGB")
    _load_clip_model()
    inputs = clip_preprocess(images=img, return_tensors="pt").to(clip_device)
    with torch.no_grad():
        img_emb = clip_model.get_image_features(**inputs)
    img_vector = img_emb.squeeze().tolist()

    # Build MediaAsset and ImageAsset records.
    # Write GraphAr Parquet files to GCS.
```

### Document Pipeline (document.py)

Document ingestion supports PDF, DOCX, PPTX, CSV, TSV, and Excel files. The
pipeline extracts text, splits it into chunks, embeds with a text model, and
stores DocChunk vertices.

```python
import os
import pandas as pd
import pptx
import docx
import uuid

from marker_pdf import MarkerPDF

def ingest_document(bucket: str, key: str):
    tmp_path = f"/tmp/{uuid.uuid4()}"
    gcs_client.download_file(bucket, key, tmp_path)

    ext = os.path.splitext(key)[1].lower()
    text_content = ""

    if ext == ".pdf":
        text_content = MarkerPDF().convert_to_text(tmp_path)
    elif ext == ".docx":
        doc = docx.Document(tmp_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text]
        text_content = "\n".join(paragraphs)
    elif ext in [".pptx", ".ppt"]:
        pres = pptx.Presentation(tmp_path)
        slides_text = []
        for slide in pres.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    slides_text.append(shape.text)
        text_content = "\n".join(slides_text)
    elif ext in [".csv", ".tsv", ".xlsx", ".xls"]:
        if ext == ".csv":
            df = pd.read_csv(tmp_path)
        elif ext == ".tsv":
            df = pd.read_csv(tmp_path, sep="\t")
        else:
            df = pd.read_excel(tmp_path)
        rows_text = []
        for _, row in df.iterrows():
            row_str = ", ".join(f"{col}: {row[col]}" for col in df.columns)
            rows_text.append(row_str)
        text_content = "\n".join(rows_text)
    else:
        with open(tmp_path, "r", errors="ignore") as f:
            text_content = f.read()

    if not text_content:
        print(f"No extractable text in {key}")
        return

    chunks = split_to_chunks(text_content)
    embeddings = [text_embed_model.encode([c])[0].tolist() for c in chunks]

    # Build MediaAsset and DocChunk records.
    # Write GraphAr Parquet files to GCS.
```

## Query Engine (retikon_core.query_engine)

The query engine supports multimodal retrieval with text, image, and audio
search. It uses DuckDB with HTTPFS to read Parquet files in GCS.

### Query Embeddings

For text queries, the system generates:

- Text embedding for document and transcript search.
- CLIP text embedding for image similarity.
- CLAP text embedding for audio similarity.

### DuckDB Views and Similarity Search

```python
query_text = params.get("query", "")
if not query_text and not params.get("image_base64"):
    return {"error": "No query provided."}

text_vec = text_embedding_model.encode([query_text])[0].tolist() if query_text else None
image_query_vec = None
audio_query_vec = None

if query_text:
    image_query_vec = clip_model.encode_text(query_text).squeeze().tolist()
    audio_query_vec = clap_model.get_text_embedding(query_text).squeeze().tolist()

con = duckdb.connect(database=":memory:")
con.execute("INSTALL httpfs; LOAD httpfs;")

graph_bucket = os.environ["GRAPH_BUCKET"]
base_path = f"https://storage.googleapis.com/{graph_bucket}/retikon_v2"

con.execute(f"""
    CREATE TEMP VIEW all_doc_chunks AS
    SELECT core.id, core.media_asset_id, text.content, vector.text_vector
    FROM '{base_path}/vertices/DocChunk/core/*.parquet' AS core
    JOIN '{base_path}/vertices/DocChunk/text/*.parquet' AS text ON core.id = text.id
    JOIN '{base_path}/vertices/DocChunk/vector/*.parquet' AS vector ON core.id = vector.id;
""")

con.execute(f"""
    CREATE TEMP VIEW all_transcripts AS
    SELECT core.id, core.media_asset_id, core.start_ms, text.content, vector.text_embedding
    FROM '{base_path}/vertices/Transcript/core/*.parquet' AS core
    JOIN '{base_path}/vertices/Transcript/text/*.parquet' AS text ON core.id = text.id
    JOIN '{base_path}/vertices/Transcript/vector/*.parquet' AS vector ON core.id = vector.id;
""")

con.execute(f"""
    CREATE TEMP VIEW all_images AS
    SELECT core.id, core.media_asset_id, vector.clip_vector
    FROM '{base_path}/vertices/ImageAsset/core/*.parquet' AS core
    JOIN '{base_path}/vertices/ImageAsset/vector/*.parquet' AS vector ON core.id = vector.id;
""")

con.execute(f"""
    CREATE TEMP VIEW all_audio AS
    SELECT core.id, core.media_asset_id, vector.clap_embedding
    FROM '{base_path}/vertices/AudioClip/core/*.parquet' AS core
    JOIN '{base_path}/vertices/AudioClip/vector/*.parquet' AS vector ON core.id = vector.id;
""")
```

Similarity search is performed against these views using cosine distance (via
DuckDB vector functions or the vss extension). Results from text, image, and
audio searches are merged and ranked by similarity score.

### Reverse Image Search

The query API accepts `image_base64` for image-to-image search. The service
decodes the image, computes a CLIP image embedding, and searches the ImageAsset
table for similar vectors.

```python
from PIL import Image
import base64
import io

image_data = params.get("image_base64")
if image_data:
    image_bytes = base64.b64decode(image_data)
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    retikon_core.query_engine.query_runner.load_clip_model()
    query_vector = (
        retikon_core.query_engine.query_runner.clip_model
        .encode_image(retikon_core.query_engine.query_runner.clip_preprocess(img).to(device))
        .squeeze()
        .tolist()
    )
    results = retikon_core.query_engine.query_runner.search_by_image_vector(query_vector)
    return {"results": results}
```

### Result Format

Results are returned as a list of hits across modalities.

```json
{
  "results": [
    {
      "file": "gs://my-retikon-raw-ingest-bucket/raw/docs/report.pdf",
      "position": null,
      "snippet": "... Apollo program succeeded in landing humans on the Moon ...",
      "score": 0.02
    },
    {
      "file": "gs://my-retikon-raw-ingest-bucket/raw/videos/launch.mp4",
      "position": "120000ms",
      "snippet": "... launching the Apollo 11 mission ...",
      "score": 0.04
    },
    {
      "file": "gs://my-retikon-raw-ingest-bucket/raw/images/rocket.png",
      "position": null,
      "snippet": "",
      "score": 0.05
    },
    {
      "file": "gs://my-retikon-raw-ingest-bucket/raw/audio/applause.wav",
      "position": null,
      "snippet": "",
      "score": 0.07
    }
  ]
}
```

## Summary of v2.5 Updates

- Clean module split: `retikon_core` for core logic and `gcp_adapter` for GCP
  entry points.
- GraphAr layout is strict and versioned under `retikon_v2/` with YAML
  definitions and UUIDv4 keys.
- Multimodal ingestion: audio CLAP embeddings, video 5-minute cap, and extended
  document support (DOCX, PPTX, CSV, XLSX).
- Query upgrades: CLIP text, CLAP text, reverse image search, HNSW indexes, and
  0..1 similarity scoring.
- DuckDB to GCS auth uses ADC/Workload Identity with credential_chain secrets,
  plus a fallback GCS extension path.
- Reliability and security: Firestore idempotency, raw size caps, Eventarc DLQ,
  and X-API-Key protection for the query API.

## Sprint Plan (2-week sprints)

This section turns the ready-to-build backlog into detailed sprint-by-sprint
implementation notes. Each sprint has a goal, scoped epics, and concrete
deliverables with testing and exit criteria.

### Baseline decisions (baked in)

- DuckDB to GCS auth uses ADC/Workload Identity via DuckDB Secrets Manager
  `credential_chain`. A fallback path uses the community GCS extension with ADC
  if the primary route fails.
- Vector search uses DuckDB vss with `CREATE INDEX ... USING HNSW`.
- GraphAr layout is strict with YAML definitions and UUIDv4 string keys for all
  vertex IDs.
- Idempotency uses a Firestore state-lock wrapper to handle at-least-once
  Eventarc delivery.
- Ops controls include a DLQ via Pub/Sub retries, max instance caps, JSON
  logging, and a raw-bucket lifecycle rule.
- Chunking uses a 512 token target with 50 token overlap (approx 2000 chars with
  200 chars overlap).
- Media formats use a permissive whitelist aligned with ffmpeg support.
- Hard caps: video 300 seconds, audio 20 minutes, raw download limit 500 MB
  (configurable).
- Query auth uses `X-API-Key`.
- Scoring uses similarity in the 0..1 range (higher is better).
- Frontend: minimal React Dev Console in Sprint 5.
- Embedding dimensions: text 768 (BGE base), image 512 (CLIP ViT-B/32), audio
  512 (CLAP HTSAT fused).
- Dev Console hosting: GCS static site (optionally fronted by Cloud CDN).
- Embedding model defaults are Hugging Face:
  - Text: `BAAI/bge-base-en-v1.5`
  - Image: `openai/clip-vit-base-patch32`
  - Audio: `laion/clap-htsat-fused`

### Development prerequisites and setup

This is the minimum baseline needed before engineering work starts.

#### Accounts and access

- GCP project exists and billing is enabled.
- Engineers have `Owner` or `Editor` access during initial setup, with a plan
  to reduce privileges later.
- Terraform state bucket exists and is writable by CI and devs.

#### Required GCP APIs

Enable these APIs in the target project:

- `run.googleapis.com` (Cloud Run)
- `eventarc.googleapis.com` (Eventarc)
- `storage.googleapis.com` (GCS)
- `artifactregistry.googleapis.com` (Artifact Registry)
- `firestore.googleapis.com` (Firestore)
- `secretmanager.googleapis.com` (Secret Manager)
- `pubsub.googleapis.com` (Pub/Sub)
- `cloudscheduler.googleapis.com` (Cloud Scheduler)
- `iam.googleapis.com` (IAM)
- `cloudresourcemanager.googleapis.com` (Project metadata)
- `logging.googleapis.com` (Cloud Logging)
- `monitoring.googleapis.com` (Cloud Monitoring)

#### IAM and Workload Identity

- Cloud Run services must run as dedicated service accounts.
- `sa_ingest` needs GCS read on raw bucket and read/write on graph bucket.
- `sa_query` needs read access on graph bucket.
- `sa_index_builder` needs read access on graph bucket and write access on the
  snapshot prefix.
- For local dev, use ADC via `gcloud auth application-default login`.

#### Secrets and config

- Secret Manager naming convention (recommended):
  - `retikon-query-api-key`
- Environment variables required at runtime:
  - `RAW_BUCKET`, `GRAPH_BUCKET`, `GRAPH_PREFIX`, `ENV`, `LOG_LEVEL`
  - `MAX_RAW_BYTES`, `MAX_VIDEO_SECONDS`, `MAX_AUDIO_SECONDS`
  - `CHUNK_TARGET_TOKENS`, `CHUNK_OVERLAP_TOKENS`
  - `SNAPSHOT_URI` (query service)
  - `DUCKDB_GCS_FALLBACK` (optional)
- Local `.env` file for dev (non-prod only).

#### Local tooling

- Python 3.10+
- Docker and Docker Compose
- Terraform 1.5+
- gcloud CLI
- Node.js 18+ (Dev Console)
- ffmpeg and ffprobe
- poppler-utils (PDF extraction)
- git

#### Model caching

- Set `HF_HOME` and `TRANSFORMERS_CACHE` to a local writable directory.
- Pre-download model weights for:
  - `BAAI/bge-base-en-v1.5`
  - `openai/clip-vit-base-patch32`
  - `laion/clap-htsat-fused`

#### Local emulators (optional but recommended)

- Firestore emulator for idempotency tests.
- Use `gcloud emulators firestore start` and point SDK to `FIRESTORE_EMULATOR_HOST`.

#### Healthcheck parquet

- Create a small parquet file at:
  - `gs://<graph-bucket>/retikon_v2/healthcheck.parquet`
- The file can contain a single row with a minimal schema. It is only used to
  validate DuckDB auth paths on service startup.

#### Test fixtures

- Ensure small fixtures are available under `tests/fixtures/`.
- Keep fixture sizes under 5 MB to keep CI fast.

#### CI service accounts (recommended roles)

- Artifact Registry Writer for image pushes.
- Cloud Run Admin for deploy steps (if CI deploys).
- Storage Object Admin on the Terraform state bucket.

### Implementation defaults (to unblock development)

These defaults can be used immediately and are safe to revise later under the
additive schema evolution rules.

#### Tokenizer and chunking

- Tokenizer: Hugging Face `AutoTokenizer` from `BAAI/bge-base-en-v1.5`.
- Chunking: sliding window of 512 tokens with 50 token overlap.
- Use `offset_mapping` to map token ranges back to `char_start` and `char_end`.
- Store `token_start`, `token_end`, and `token_count` in each chunk core record.

#### File allowlists (defaults)

- Docs: `.pdf`, `.txt`, `.md`, `.rtf`, `.docx`, `.doc`, `.pptx`, `.ppt`, `.csv`,
  `.tsv`, `.xlsx`, `.xls`
- Images: `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.tiff`, `.gif` (first frame)
- Audio: `.mp3`, `.wav`, `.flac`, `.m4a`, `.aac`, `.ogg`, `.opus`
- Video: `.mp4`, `.mov`, `.mkv`, `.webm`, `.avi`, `.mpeg`, `.mpg`
- Validation rule: extension and content type must both match the modality.

### GraphAr schema reference (proposed)

Vector columns use `list<float32>` with fixed lengths per modality.

#### MediaAsset

- core:
  - `id`: string (UUIDv4)
  - `uri`: string
  - `media_type`: string (`document`, `image`, `audio`, `video`)
  - `content_type`: string
  - `size_bytes`: int64
  - `source_bucket`: string
  - `source_object`: string
  - `source_generation`: string
  - `checksum`: string (md5 or crc32c)
  - `duration_ms`: int64 (nullable)
  - `width_px`: int32 (nullable)
  - `height_px`: int32 (nullable)
  - `frame_count`: int32 (nullable)
  - `sample_rate_hz`: int32 (nullable)
  - `channels`: int32 (nullable)
  - `created_at`: timestamp
  - `pipeline_version`: string
  - `schema_version`: string

#### DocChunk

- core:
  - `id`: string (UUIDv4)
  - `media_asset_id`: string (UUIDv4)
  - `chunk_index`: int32
  - `char_start`: int32
  - `char_end`: int32
  - `token_start`: int32
  - `token_end`: int32
  - `token_count`: int32
  - `embedding_model`: string
  - `pipeline_version`: string
  - `schema_version`: string
- text:
  - `id`: string (UUIDv4)
  - `content`: string
- vector:
  - `id`: string (UUIDv4)
  - `text_vector`: list<float32>

#### ImageAsset

- core:
  - `id`: string (UUIDv4)
  - `media_asset_id`: string (UUIDv4)
  - `frame_index`: int32 (nullable, still images are null)
  - `timestamp_ms`: int64 (nullable, still images are null)
  - `width_px`: int32
  - `height_px`: int32
  - `embedding_model`: string
  - `pipeline_version`: string
  - `schema_version`: string
- vector:
  - `id`: string (UUIDv4)
  - `clip_vector`: list<float32>

#### Transcript

- core:
  - `id`: string (UUIDv4)
  - `media_asset_id`: string (UUIDv4)
  - `segment_index`: int32
  - `start_ms`: int64
  - `end_ms`: int64
  - `language`: string
  - `embedding_model`: string
  - `pipeline_version`: string
  - `schema_version`: string
- text:
  - `id`: string (UUIDv4)
  - `content`: string
- vector:
  - `id`: string (UUIDv4)
  - `text_embedding`: list<float32>

#### AudioClip

- core:
  - `id`: string (UUIDv4)
  - `media_asset_id`: string (UUIDv4)
  - `start_ms`: int64
  - `end_ms`: int64
  - `sample_rate_hz`: int32
  - `channels`: int32
  - `embedding_model`: string
  - `pipeline_version`: string
  - `schema_version`: string
- vector:
  - `id`: string (UUIDv4)
  - `clap_embedding`: list<float32>

#### DerivedFrom (edge)

- adj_list:
  - `src_id`: string (UUIDv4 child)
  - `dst_id`: string (UUIDv4 parent MediaAsset)

#### NextKeyframe (edge)

- adj_list:
  - `src_id`: string (UUIDv4)
  - `dst_id`: string (UUIDv4)

#### NextTranscript (edge)

- adj_list:
  - `src_id`: string (UUIDv4)
  - `dst_id`: string (UUIDv4)

### Epics

- E1 Repo + DevEx: repo structure, tooling, tests, config and logging.
- E2 GraphAr spec + schemas + writers: layout, YAMLs, Parquet schemas.
- E3 Ingestion service: Eventarc CloudEvent routing to pipelines.
- E4 Pipelines: document, image, audio, and video ingestion.
- E5 Query service: warm start, snapshot usage, multimodal retrieval.
- E6 IndexBuilder: HNSW build and snapshot upload.
- E7 GCP IaC + CI/CD: Terraform and pipelines.
- E8 Reliability + Observability + Cost controls: DLQ, limits, logging, metrics.
- E9 Security: API key auth, IAM, secrets.
- E10 Frontend Dev Console.

### Sprint 1 (Weeks 1-2) - Foundations and deployable skeleton

#### Goal

Establish repo structure, baseline services, baseline Terraform, and CI that
ships a deployable skeleton with passing tests.

#### Scope (Epics)

E1, E3, E7

#### Detailed tasks

- E1 Repo and DevEx
  - Create monorepo structure:
    - `retikon_core/` (core logic)
    - `gcp_adapter/` (Cloud Run entry points)
    - `infrastructure/terraform/`
  - Add dependency management with pinned versions and a lockfile strategy.
    - Recommended: `requirements.in` + `requirements.txt` via pip-tools, or a
      single `pyproject.toml` with an explicit lock file.
  - Add `Makefile` targets:
    - `lint`, `fmt`, `test`, `run-ingest`, `run-query`, `build-ingest`,
      `build-query`.
  - Add code quality tooling:
    - `ruff` for linting
    - `black` for formatting
    - `mypy` for types
  - Add `.dockerignore`, `.gitignore`, and `.editorconfig`.
  - Implement config loader in `retikon_core/config.py`.
    - Define a `Config` object (dataclass or pydantic) with required env vars:
      `RAW_BUCKET`, `GRAPH_BUCKET`, `GRAPH_PREFIX`, `ENV`, `LOG_LEVEL`,
      `MAX_RAW_BYTES`, `MAX_VIDEO_SECONDS`, `MAX_AUDIO_SECONDS`,
      `CHUNK_TARGET_TOKENS`, `CHUNK_OVERLAP_TOKENS`.
  - Implement structured JSON logger in `retikon_core/logging.py`.
    - Include `service`, `env`, `request_id`, `correlation_id`, `severity`,
      `duration_ms`, and `version`.
    - Correlation ID should come from a request header or be generated.
  - Add error taxonomy in `retikon_core/errors.py`.
    - `RecoverableError`, `PermanentError`, `AuthError`, `ValidationError`.
  - Add pytest harness scaffolding:
    - `tests/fixtures/` folder
    - `tests/conftest.py`
    - sample test placeholders

- E7 Terraform baseline
  - Add provider config and remote state pattern (documented with a sample
    `backend.tf.example`).
  - Define variables: project, region, env, bucket names, service names, image
    tag, and service memory limits.
  - Create GCS buckets: `raw_bucket` and `graph_bucket` with uniform bucket
    level access.
  - Add lifecycle rule block (placeholder, no-op for now).
  - Create Artifact Registry repo.
  - Create service accounts: `sa_ingest`, `sa_query`, `sa_index_builder`.
  - Attach minimum IAM roles:
    - `sa_ingest`: read raw bucket and read/write graph bucket.
    - `sa_query`: read graph bucket.
  - Create Cloud Run services:
    - `ingestion-service` (internal)
    - `query-service` (public but auth-guarded later)
  - Add placeholder env vars on both services and output URLs + bucket names.

- E3 Service skeletons
- Implement `GET /health` on both services.
    - Return JSON with `status`, `service`, `version`, `commit`.
  - Implement `POST /ingest` to accept CloudEvent JSON.
    - Validate structure, return `202` and a trace ID.
  - Implement `POST /query` to accept JSON and return a stub response.
  - Add request validation using pydantic or dataclasses.
  - Add basic integration test:
    - start the container locally
    - hit `/health` and assert 200

- E7 CI/CD bootstrap
  - CI workflow: run lint + unit tests on PR.
  - Build workflow: Docker build steps for ingestion and query images.
  - Placeholder steps for image push on release tags.

#### Exit criteria

- `terraform apply` deploys both services.
- CI passes on a clean PR.
- `/health` returns OK on Cloud Run for both services.

### Sprint 2 (Weeks 3-4) - GraphAr spec, schemas, and writers

#### Goal

Lock the GraphAr physical layout, define YAML schemas, and ship Parquet writer
utilities with tests.

#### Scope (Epics)

E2, E1

#### Detailed tasks

- E2 GraphAr physical layout and ID policy
  - Canonical root prefix: `gs://<graph-bucket>/retikon_v2/`.
  - Directories:
    - `vertices/<Type>/{core,text,vector}/part-<uuid>.parquet`
    - `edges/<Type>/adj_list/part-<uuid>.parquet`
  - `prefix.yml` per vertex and edge type.
  - All vertex IDs are UUIDv4 strings.
  - All FK fields are UUIDv4 string references (`media_asset_id`, `parent_id`).
  - Schema evolution is additive-only with `union_by_name=true` for queries.

- E2 YAML definitions
  - Create YAMLs:
    - `retikon_core/schemas/graphar/MediaAsset/prefix.yml`
    - `retikon_core/schemas/graphar/DocChunk/prefix.yml`
    - `retikon_core/schemas/graphar/ImageAsset/prefix.yml`
    - `retikon_core/schemas/graphar/Transcript/prefix.yml`
    - `retikon_core/schemas/graphar/AudioClip/prefix.yml`
    - `retikon_core/schemas/graphar/DerivedFrom/prefix.yml`
    - `retikon_core/schemas/graphar/NextKeyframe/prefix.yml`
    - `retikon_core/schemas/graphar/NextTranscript/prefix.yml`
  - Each YAML includes:
    - type name, schema version, column definitions, and file layout.
  - Validate YAMLs with an internal checker script.

- E2 Parquet schemas and writer library
  - `retikon_core/storage/paths.py`
    - build canonical GCS paths for vertex, edge, and manifest locations.
  - `retikon_core/storage/schemas.py`
    - pyarrow schemas for core, text, vector tables.
  - `retikon_core/storage/writer.py`
    - write to a local temp file and upload to GCS.
    - finalize to `part-<uuid>.parquet` with deterministic column order.
  - `retikon_core/storage/manifest.py`
    - emit `manifest.json` with counts, pipeline version, schema version,
      timestamps, and checksums.
  - Include a `schema_version` field in each vertex core record.

- E1 Test fixtures
  - Add small fixtures: `pdf`, `docx`, `pptx`, `csv`, `xlsx`, `jpg`, `png`,
    `wav`, `mp4`.
  - Unit tests:
    - write each vertex parquet locally and read back to verify schema.
    - path builder output matches expected GCS paths.
    - schema evolution merge works with `union_by_name=true`.

#### Exit criteria

- YAML schemas and Parquet writers exist and are validated.
- Local end-to-end "write GraphAr parquet" test passes.

### Sprint 3 (Weeks 5-6) - Ingestion router, Firestore idempotency, doc and image pipelines

#### Goal

Route Eventarc events to pipelines, suppress duplicates safely, and ship
document and image ingestion end-to-end.

#### Scope (Epics)

E3, E4, E7

#### Detailed tasks

- E3 Eventarc parsing and router
  - Parse CloudEvent fields: bucket, object, generation, content type, size.
  - Router rules:
    - `raw/docs/` -> document pipeline
    - `raw/images/` -> image pipeline
    - `raw/audio/` -> audio pipeline (stub in this sprint)
    - `raw/videos/` -> video pipeline (stub in this sprint)
  - Extension whitelist enforcement with a permissive list.
    - Config: `ALLOWED_DOC_EXT`, `ALLOWED_IMAGE_EXT`, `ALLOWED_AUDIO_EXT`,
      `ALLOWED_VIDEO_EXT`.
  - Object size guard:
    - read metadata size, enforce `MAX_RAW_BYTES` (default 500 MB).
  - Secure download helper:
    - stream download to `/tmp`, validate size again, cleanup in `finally`.
  - Error classification:
    - `PermanentError` for unsupported formats or oversize files.
    - `RecoverableError` for transient download or model errors.

- E3 Firestore idempotency wrapper
  - Firestore collection: `ingestion_events`.
  - Doc ID: `sha256(bucket/object#generation)`.
  - Fields:
    - `status`: PROCESSING, COMPLETED, FAILED
    - `attempt_count`, `error_code`, `error_message`
    - `object_generation`, `object_size`, `pipeline_version`
    - `started_at`, `updated_at`, `expires_at`
  - Logic:
    - If COMPLETED: short-circuit and return 200.
    - If PROCESSING and not expired: return 202 without reprocessing.
    - If FAILED or PROCESSING expired (>10 minutes): reprocess.
  - Optional TTL policy on `expires_at`.
  - Tests using Firestore emulator or a mocked client.

- E4 Document pipeline
  - Text extraction for:
    - PDF, DOCX, PPTX, CSV, TSV, XLSX, XLS
  - Chunker:
    - target 512 tokens and 50 token overlap
    - approximate 1 token = 4 chars (2000 chars + 200 overlap)
    - stable chunk IDs using UUIDv5 from `media_asset_id` and chunk index
  - Text embedder interface:
    - `TextEmbedder.encode(texts) -> list[list[float]]`
  - GraphAr outputs:
    - `MediaAsset` core
    - `DocChunk` core, text, vector
    - `DerivedFrom` edges
  - Emit manifest with counts and timings.

- E4 Image pipeline
  - Safe decode using Pillow with EXIF handling:
    - `ImageOps.exif_transpose`, then `convert("RGB")`
  - CLIP embedder:
    - lazy load, cache per process
  - GraphAr outputs:
    - `MediaAsset` core
    - `ImageAsset` core and vector
    - `DerivedFrom` edges

- E7 IaC updates
  - Provision Firestore (Native mode) or document manual steps if shared.
  - Add IAM for `sa_ingest` to access Firestore.
  - Add Eventarc trigger: raw bucket finalize -> `/ingest`.

#### Exit criteria

- raw doc or image upload triggers ingestion via Eventarc.
- GraphAr parquet appears in `retikon_v2/`.
- Duplicate events do not create duplicate outputs.

### Sprint 4 (Weeks 7-8) - Audio and video pipelines with caps

#### Goal

Ship audio and video ingestion with duration caps, format handling, and robust
error behavior.

#### Scope (Epics)

E4, E3

#### Detailed tasks

- E4 Shared media utilities
  - Ensure ffmpeg and ffprobe are in the ingestion container image.
  - Duration probe helper:
    - uses `ffprobe` to return seconds and stream info.
  - Audio normalization helper:
    - resample to 48 kHz for CLAP.
  - Media format whitelist:
    - allow common ffmpeg-supported formats (mp3, wav, m4a, mp4, mov, avi).
    - map content types to extension validation.

- E4 Audio pipeline (20 minute cap)
  - Enforce `MAX_AUDIO_SECONDS=1200` by default.
  - Transcribe using Whisper with segment timestamps.
  - Embed transcript text using the standard text embedder.
  - Compute CLAP embedding for the audio clip.
  - GraphAr outputs:
    - `MediaAsset` core
    - `Transcript` core, text, vector
    - `AudioClip` core, vector
    - `DerivedFrom` edges

- E4 Video pipeline (5 minute cap)
  - Enforce `MAX_VIDEO_SECONDS=300` hard cap.
  - Extract audio track and run Whisper + CLAP.
  - Frame sampling policy:
    - config `VIDEO_SAMPLE_FPS` or `VIDEO_SAMPLE_INTERVAL_SECONDS`.
  - Compute CLIP embeddings per sampled frame.
  - GraphAr outputs:
    - `MediaAsset` core
    - `ImageAsset` keyframes (core, vector)
    - `Transcript` segments
    - `AudioClip` clip embedding
    - `DerivedFrom`, `NextKeyframe`, `NextTranscript` edges

- E3 Router completion
  - Enable audio and video routes in the router.
  - Ensure errors are classified as recoverable or permanent.

#### Tests

- Audio and video duration cap tests:
  - audio > 20 minutes and video > 300 seconds must hard stop.
- Corruption tests:
  - truncated mp4 or bad mp3 should mark FAILED without crashing.

#### Exit criteria

- Audio and video ingestion runs end-to-end.
- Caps and format guards are enforced.
- GraphAr output is consistent across modalities.

### Sprint 5 (Weeks 9-10) - Query warm start, secure GCS auth, HNSW usage, Dev Console

#### Goal

Deliver fast query service using snapshot DB, secure GCS auth, HNSW-backed
vector search, and a minimal Dev Console.

#### Scope (Epics)

E5, E6, E9, E10

#### Detailed tasks

- E5 Secure DuckDB connection (GCS)
  - Implement `retikon_core/query_engine/warm_start.py:get_secure_connection()`.
  - Load DuckDB extensions: `httpfs` and `vss`.
  - Primary auth path:
    - `CREATE SECRET retikon_gcs (TYPE GCS, PROVIDER credential_chain);`
  - Fallback auth path (feature-flagged):
    - load community `gcs` extension, use ADC.
    - gate with `DUCKDB_GCS_FALLBACK=1`.
  - Startup self-test:
    - `read_parquet("gs://<graph-bucket>/retikon_v2/healthcheck.parquet")`.
  - Log auth diagnostics:
    - `duckdb_auth_path`, `duckdb_extension_loaded`.

- E6 and E5 Snapshot DB loading
  - Config: `SNAPSHOT_URI=gs://<graph-bucket>/retikon_v2/snapshots/retikon.duckdb`.
  - On startup:
    - download to `/tmp/retikon.duckdb`.
    - open DuckDB in read-only mode.
  - Snapshot metadata:
    - read sidecar JSON to log build timestamp and row counts.
  - Optional admin endpoint `/admin/reload-snapshot` (protected).

- E5 Query API (multimodal + score normalization)
  - Request schema:
    - `query_text?: str`
    - `image_base64?: str`
    - `top_k?: int`
  - Text query path:
    - embed text for DocChunk and Transcript.
    - CLIP text embedding for ImageAsset.
    - CLAP text embedding for AudioClip.
  - Image query path:
    - decode base64 image, compute CLIP image embedding.
  - Similarity scoring:
    - `sim = 1.0 - cosine_distance`
    - clamp to `[0.0, 1.0]`
  - Response contract:
    - `modality`, `uri`, `snippet`, `timestamp_ms`, `score`, `media_asset_id`.
  - Guardrails:
    - `top_k` max enforced.
    - reject large base64 payloads and oversized JSON bodies.

- E9 Query auth (X-API-Key)
  - Add middleware in `gcp_adapter/query_service.py`.
  - Store API key in Secret Manager, wire via env.
  - Local dev override via `.env` (non-prod only).
  - Unit tests: missing key -> 401, wrong key -> 401, correct -> 200.

- E10 Minimal React Dev Console
  - Create `frontend/dev-console/` (Vite + React).
  - UI features:
    - text input and image upload (client-side resize)
    - results list with modality icons
    - image thumbnail, audio player, and video link with timestamps
    - API key input stored in `localStorage`
    - "copy curl" button for debugging
  - Deploy target:
    - GCS static site (optionally fronted by Cloud CDN).
  - Add README instructions and smoke test steps.

#### Exit criteria

- Query service reads private GCS via ADC without HMAC keys.
- Snapshot is used and HNSW-backed queries return results.
- API key is required for the query API.
- Dev Console validates end-to-end multimodal retrieval.

#### Release note (must resolve before signoff)

- Temporary unblock: `DUCKDB_SKIP_HEALTHCHECK=1` may be used to bypass the
  DuckDB `gs://` healthcheck when credential_chain auth is failing. This must
  be removed and the healthcheck restored before release signoff.

### Sprint 6 (Weeks 11-12) - IndexBuilder job (HNSW snapshot build + upload)

#### Goal

Automate snapshot creation with HNSW indexes and publish to GCS.

#### Scope (Epics)

E6, E7

#### Detailed tasks

- E6 IndexBuilder implementation
  - `retikon_core/query_engine/index_builder.py`.
  - Create DuckDB file `/tmp/retikon.duckdb`.
  - Load Parquet tables from GraphAr:
    - DocChunk vectors
    - Transcript vectors
    - ImageAsset vectors
    - AudioClip vectors
  - Use GraphAr manifests to align core/text/vector files per ingestion run.
    - Join rows by `file_row_number` within the same manifest group.
    - Fail fast if manifests are missing but GraphAr data exists.
  - Install/load `vss` and build HNSW indexes:
    - `CREATE INDEX ... USING HNSW` per table.
  - `CHECKPOINT` and close DB.
  - Emit build report JSON with row counts, index sizes, build time.
  - Upload snapshot and report:
    - `gs://<graph-bucket>/retikon_v2/snapshots/retikon.duckdb`
    - `gs://<graph-bucket>/retikon_v2/snapshots/retikon.duckdb.json`

- E7 Cloud Run Job and triggers
  - Create Cloud Run Job `index-builder`.
  - Grant SA read access to graph Parquet and write access to snapshot path.
  - Add manual trigger script: `scripts/run_index_builder.sh`.
  - Optional schedule: Cloud Scheduler -> Pub/Sub -> Cloud Run Jobs execute.
  - Set memory and timeout for index build.

#### Tests

- Local integration: build snapshot from fixtures and query it.
- Regression: benchmark query latency with and without HNSW.

#### Exit criteria

- Snapshot build is repeatable and deployable as a Cloud Run Job.
- Query service can cold start, download snapshot, and serve queries.

### Sprint 7 (Weeks 13-14) - Operational hardening

#### Goal

Reduce failure impact, cap costs, and make operational behavior visible.

#### Scope (Epics)

E8, E7

#### Detailed tasks

- E8 DLQ and retries
  - Define Pub/Sub topic for Eventarc transport.
  - Configure DLQ topic + subscription and publish failures to DLQ.
  - Implement DLQ handler tool:
    - list messages
    - show error reason
    - replay safely
  - Add a runbook for replay and cleanup.
  - Note: GCS Eventarc triggers use managed transport; custom Pub/Sub transport
    topics are not supported for these triggers. Keep the transport topic for
    future Pub/Sub-triggered pipelines.

- E8 Concurrency and scaling limits
  - Terraform:
    - ingestion `max_instance_count=10`
    - ingestion `concurrency=1`
    - query `concurrency` set to 5 to 20 (tune later)
  - Add basic per-modality rate limiting (in-memory token bucket).

- E8 JSON logging and metrics
  - Ensure all services log JSON consistently.
  - Required fields:
    - `modality`, `duration_ms`, `bytes_downloaded`, `processing_ms`,
      `media_asset_id`
  - Add metrics export:
    - OpenTelemetry optional
    - Cloud Monitoring dashboards
  - Alerts:
    - ingestion error rate
    - query p95 latency
    - DLQ non-empty

- E8 Cost controls
  - Raw bucket lifecycle: delete `raw/` objects after 7 days.
  - Graph bucket retention: retain forever.
  - Enforce `MAX_RAW_BYTES` on ingest.
  - Add `MAX_FRAMES_PER_VIDEO` guard derived from fps and duration cap.

#### Exit criteria

- Failures go to DLQ after retries.
- Scaling is capped and safe.
- Logs and metrics are queryable by modality and media ID.
- Raw bucket auto-cleans.

### Sprint 8 (Weeks 15-16) - Polish and release readiness

#### Goal

Stabilize performance, document operations, and prepare for release.

#### Scope (Epics)

E8 plus cross-cutting work

#### Detailed tasks

- Load testing:
  - query QPS target
  - ingest throughput target
  - capture p95 latency and cost signals
  - scripts: `scripts/load_test_query.py`, `scripts/load_test_ingest.py`
  - results record: `Dev Docs/Load-Testing.md`
- Cold-start optimization:
  - lazy model load, warm-path caching, reuse model instances
  - cache stub embedders to avoid per-request instantiation
- Snapshot refresh strategy:
  - define cadence, backfill behavior, and rollback steps
  - documented in `Dev Docs/Snapshot-Refresh-Strategy.md`
- Documentation pack:
  - local dev, deployment, ops runbook, schema reference
  - `Dev Docs/Local-Development.md`
  - `Dev Docs/Deployment.md`
  - `Dev Docs/Operations-Runbook.md`
  - `Dev Docs/Schema-Reference.md`
- Golden demo dataset and scripted demo steps.
  - `scripts/upload_demo_dataset.py`
  - `Dev Docs/Golden-Demo.md`
- Security review checklist:
  - IAM least privilege
  - secret rotation plan
  - API key rotation and audit
  - `Dev Docs/Security-Checklist.md`
  - `Dev Docs/Release-Checklist.md`

#### Exit criteria

- Load test results meet targets.
- Documentation is complete and reviewed.
- Release checklist is satisfied.

### Per-story checklist (attach to every Jira story)

- Add unit tests.
- Add integration tests where applicable.
- Update README or dev docs.
- Add structured logs.
- Add config and env var docs.
- Add failure-mode notes (expected behavior on error).

### Decisions locked for ticketing

- Embedding dimensions: text 768, image 512, audio 512.
- Dev Console hosting: GCS static site (optionally with Cloud CDN).

## References

- Retikon v2 design notes and original build kit documentation.
- GCP Eventarc trigger configuration for GCS (Terraform examples).
