FROM python:3.10-slim

ARG APP_MODULE=gcp_adapter.query_service:app
ENV APP_MODULE=${APP_MODULE}

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY retikon_core/ /app/retikon_core/
COPY gcp_adapter/ /app/gcp_adapter/

ENV PYTHONPATH=/app

CMD ["sh", "-c", "uvicorn ${APP_MODULE} --host 0.0.0.0 --port 8080"]
