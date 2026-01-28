# sdk/python/retikon_sdk/client.py

Edition: Core

## Classes
- `RetikonClient`: Data structure or helper class for Retikon Client, so clients can call the APIs safely.
  - Methods
    - `_headers`: Internal helper that headers, so clients can call the APIs safely.
    - `_request`: Internal helper that requests it, so clients can call the APIs safely.
    - `ingest`: Accepts content to ingest and starts processing, so clients can call the APIs safely.
    - `query`: Runs a search request and returns results, so clients can call the APIs safely.
    - `health`: Reports service health, so clients can call the APIs safely.
    - `reload_snapshot`: Function that reload snapshot, so clients can call the APIs safely.
