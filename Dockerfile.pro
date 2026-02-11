FROM python:3.10-slim

ARG PRELOAD_MODELS=1
ARG MODEL_DIR=/app/models
ARG INSTALL_OCR=0
ARG EXPORT_ONNX=0
ARG QUANTIZE_ONNX=0

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    libsndfile1 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir setuptools wheel && \
    pip install --no-cache-dir --no-build-isolation -r /app/requirements.txt
COPY requirements-ocr.txt /app/requirements-ocr.txt
RUN if [ "${INSTALL_OCR}" = "1" ]; then \
        apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-eng && \
        pip install --no-cache-dir -r /app/requirements-ocr.txt && \
        rm -rf /var/lib/apt/lists/* ; \
    fi

ENV MODEL_DIR=${MODEL_DIR}
ENV HF_HOME=${MODEL_DIR}
ENV TRANSFORMERS_CACHE=${MODEL_DIR}

COPY scripts/ /app/scripts/
COPY retikon_core/ /app/retikon_core/
COPY retikon_gcp/ /app/retikon_gcp/
COPY gcp_adapter/ /app/gcp_adapter/

ENV PYTHONPATH=/app

RUN if [ "${PRELOAD_MODELS}" = "1" ]; then \
        EXPORT_ONNX="${EXPORT_ONNX}" QUANTIZE_ONNX="${QUANTIZE_ONNX}" \
        python /app/scripts/download_models.py ; \
    fi

ARG APP_MODULE=gcp_adapter.query_service:app
ENV APP_MODULE=${APP_MODULE}

CMD ["sh", "-c", "uvicorn ${APP_MODULE} --host 0.0.0.0 --port 8080"]
