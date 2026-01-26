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

## Run services locally

```bash
make run-ingest
make run-query
```

## Docker build (skip model downloads)

```bash
docker build -t retikon-dev --build-arg PRELOAD_MODELS=0 .
```

## Tests

```bash
make lint
make test
```
