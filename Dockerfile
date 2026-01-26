FROM python:3.10-slim

ARG APP_MODULE=gcp_adapter.query_service:app
ENV APP_MODULE=${APP_MODULE}
ARG PRELOAD_MODELS=1
ARG MODEL_DIR=/app/models

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    libsndfile1 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

ENV MODEL_DIR=${MODEL_DIR}
ENV HF_HOME=${MODEL_DIR}
ENV TRANSFORMERS_CACHE=${MODEL_DIR}

COPY scripts/ /app/scripts/
COPY retikon_core/ /app/retikon_core/
COPY gcp_adapter/ /app/gcp_adapter/

ENV PYTHONPATH=/app

RUN if [ "${PRELOAD_MODELS}" = "1" ]; then \
        python /app/scripts/download_models.py ; \
    fi

CMD ["sh", "-c", "uvicorn ${APP_MODULE} --host 0.0.0.0 --port 8080"]
