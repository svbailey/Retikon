# retikon_core/edge/buffer.py

Edition: Core

## Functions
- `_atomic_write_bytes`: Internal helper that atomic write bytes, so edge ingestion is resilient.
- `_atomic_write_json`: Internal helper that atomic write JSON, so edge ingestion is resilient.

## Classes
- `BufferItem`: Data structure or helper class for Buffer Item, so edge ingestion is resilient.
  - Methods
    - `read_bytes`: Function that reads bytes, so edge ingestion is resilient.
- `BufferStats`: Data structure or helper class for Buffer Stats, so edge ingestion is resilient.
- `EdgeBuffer`: Data structure or helper class for Edge Buffer, so edge ingestion is resilient.
  - Methods
    - `__init__`: Sets up the object, so edge ingestion is resilient.
    - `add_bytes`: Function that add bytes, so edge ingestion is resilient.
    - `list_items`: Function that lists items, so edge ingestion is resilient.
    - `stats`: Function that stats, so edge ingestion is resilient.
    - `prune`: Function that prune, so edge ingestion is resilient.
    - `replay`: Function that replay, so edge ingestion is resilient.
    - `_remove_item`: Internal helper that remove item, so edge ingestion is resilient.
