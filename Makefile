PYTHON ?= python
APP_QUERY ?= local_adapter.query_service:app
APP_INGEST ?= local_adapter.ingestion_service:app
APP_QUERY_PRO ?= gcp_adapter.query_service:app
APP_INGEST_PRO ?= gcp_adapter.ingestion_service:app
DOCKERFILE_PRO ?= Dockerfile.pro

.PHONY: lint fmt test run-ingest run-query build-ingest build-query run-gcp-ingest run-gcp-query

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m mypy retikon_core gcp_adapter

fmt:
	$(PYTHON) -m black .

test:
	$(PYTHON) -m pytest

run-ingest:
	PYTHONPATH=. $(PYTHON) -m uvicorn $(APP_INGEST) --host 0.0.0.0 --port 8081 --reload

run-query:
	PYTHONPATH=. $(PYTHON) -m uvicorn $(APP_QUERY) --host 0.0.0.0 --port 8080 --reload

run-gcp-ingest:
	PYTHONPATH=. $(PYTHON) -m uvicorn $(APP_INGEST_PRO) --host 0.0.0.0 --port 8081 --reload

run-gcp-query:
	PYTHONPATH=. $(PYTHON) -m uvicorn $(APP_QUERY_PRO) --host 0.0.0.0 --port 8080 --reload

build-ingest:
	docker build -f $(DOCKERFILE_PRO) -t retikon-ingest:dev --build-arg APP_MODULE=$(APP_INGEST_PRO) .

build-query:
	docker build -f $(DOCKERFILE_PRO) -t retikon-query:dev --build-arg APP_MODULE=$(APP_QUERY_PRO) .
