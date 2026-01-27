# Retikon Core Python SDK

Minimal SDK for Retikon Core local ingestion and query services.

## Install (editable)

```bash
cd sdk/python
pip install -e .
```

## Usage

```python
from retikon_sdk import RetikonClient

client = RetikonClient(
    ingest_url="http://localhost:8081",
    query_url="http://localhost:8082",
)

# Ingest a local file by path
result = client.ingest(path="/data/sample.csv", content_type="text/csv")
print(result)

# Text query (vector search)
resp = client.query(query_text="hello", top_k=5, mode="text")
print(resp["results"])

# Keyword search
resp = client.query(query_text="alarm", search_type="keyword")

# Metadata filter
resp = client.query(search_type="metadata", metadata_filters={"content_type": "application/pdf"})
```

## Notes
- The ingestion service reads local file paths, so the API must run on the same host.
- For multimodal queries, omit `mode`/`modalities` to search across all modalities.
