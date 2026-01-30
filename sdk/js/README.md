# Retikon Core JS SDK

Minimal SDK for Retikon Core local ingestion and query services.

## Usage (Node 18+ / Browser)

```js
import { RetikonClient } from "@retikon/core-sdk";

const client = new RetikonClient({
  ingestUrl: "http://localhost:8081",
  queryUrl: "http://localhost:8080",
  authToken: "JWT",
});

const ingest = await client.ingest({ path: "/data/sample.csv", contentType: "text/csv" });
console.log(ingest);

const results = await client.query({ queryText: "hello", topK: 5, mode: "text" });
console.log(results);
```

Defaults can also come from environment variables (Node):

- `RETIKON_INGEST_URL`
- `RETIKON_QUERY_URL`
- `RETIKON_AUTH_TOKEN` (or `RETIKON_JWT`)
- `RETIKON_TIMEOUT_S` (seconds) or `RETIKON_TIMEOUT_MS`

## Notes
- The ingestion service reads local file paths, so the API must run on the same host.
