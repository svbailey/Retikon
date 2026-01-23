PYTHON ?= python
APP_QUERY ?= gcp_adapter.query_service:app
APP_INGEST ?= gcp_adapter.ingestion_service:app

.PHONY: lint fmt test run-ingest run-query build-ingest build-query

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

build-ingest:
	docker build -t retikon-ingest:dev --build-arg APP_MODULE=$(APP_INGEST) .

build-query:
	docker build -t retikon-query:dev --build-arg APP_MODULE=$(APP_QUERY) .
