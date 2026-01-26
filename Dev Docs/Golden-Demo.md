# Golden Demo

This demo validates end-to-end ingestion, indexing, and query.

## Steps

1. Upload the demo dataset to the raw bucket:

```bash
RAW_BUCKET="<raw-bucket>" \
python scripts/upload_demo_dataset.py
```

2. Wait for ingestion to finish (check logs or Firestore).

3. Build the snapshot:

```bash
scripts/run_index_builder.sh
```

4. Reload the query snapshot:

```bash
curl -X POST "$QUERY_URL/admin/reload-snapshot" \
  -H "X-API-Key: $QUERY_API_KEY"
```

5. Run a text query:

```bash
curl -X POST "$QUERY_URL/query" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $QUERY_API_KEY" \
  -d '{"top_k":5,"query_text":"demo"}'
```

6. Open the Dev Console and validate results.

## Notes

- The demo uploads files into `raw/<modality>/<run-id>/`.
- Clean up demo data if needed to avoid storage costs.

## Latest run (2026-01-26)

- Run ID: `golden-20260126-130909`
- Ingestion status: 10 completed, 0 DLQ (fixtures updated to include text in PDF/PPTX/XLSX)
- Index builder execution: `retikon-index-builder-dev-wp4rf`
- Snapshot reload: `{"status":"ok","service":"retikon-query",...}`
- Query result (text="Retikon", top_k=5): returns document hits (CSV/TSV snippets)
