# Local Development

## Prerequisites

- Python 3.10+
- Docker
- Terraform 1.5+
- gcloud CLI
- ffmpeg + ffprobe
- poppler-utils

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

Create `.env` with the required variables (see `README.md`).

### Real models (optional)

Set these for real model runs (CPU-only default):

- `USE_REAL_MODELS=1`
- `MODEL_DIR=/app/models` (or a local cache path)
- `TEXT_MODEL_NAME=BAAI/bge-base-en-v1.5`
- `IMAGE_MODEL_NAME=openai/clip-vit-base-patch32`
- `AUDIO_MODEL_NAME=laion/clap-htsat-fused`
- `WHISPER_MODEL_NAME=small`
- `EMBEDDING_DEVICE=cpu`

### OCR (optional)

OCR is disabled by default. To enable OCR locally:

1) Install `tesseract-ocr` on your machine.
2) Install optional deps:

```bash
pip install -r requirements-ocr.txt
```

3) Set:

- `ENABLE_OCR=1`
- `OCR_MAX_PAGES=5` (optional)

## Run services locally

Bootstrap local config and snapshot:

```bash
retikon init
retikon doctor
```

Then run services:

```bash
make run-ingest
make run-query
```

`scripts/local_up.sh` auto-loads `.env` (and `.env.local` if present). If `.env`
doesn't exist, it will copy from `.env.example` and apply safe local defaults.
If a local snapshot is missing, it will bootstrap one automatically.

## Docker build (skip model downloads)

```bash
docker build -f Dockerfile.pro -t retikon-dev --build-arg PRELOAD_MODELS=0 .
```

## Tests

```bash
make lint
make test
```
