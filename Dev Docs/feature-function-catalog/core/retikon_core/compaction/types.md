# retikon_core/compaction/types.py

Edition: Core

## Classes
- `ManifestFile`: Data structure or helper class for Manifest File, so storage stays compact and efficient.
- `ManifestInfo`: Data structure or helper class for Manifest Info, so storage stays compact and efficient.
- `CompactionGroup`: Data structure or helper class for Compaction Group, so storage stays compact and efficient.
  - Methods
    - `file_kinds`: Function that file kinds, so storage stays compact and efficient.
    - `bytes_by_kind`: Function that bytes by kind, so storage stays compact and efficient.
    - `rows_by_kind`: Function that rows by kind, so storage stays compact and efficient.
- `CompactionBatch`: Data structure or helper class for Compaction Batch, so storage stays compact and efficient.
  - Methods
    - `bytes_by_kind`: Function that bytes by kind, so storage stays compact and efficient.
    - `rows_by_kind`: Function that rows by kind, so storage stays compact and efficient.
- `CompactionOutput`: Data structure or helper class for Compaction Output, so storage stays compact and efficient.
- `CompactionReport`: Data structure or helper class for Compaction Report, so storage stays compact and efficient.
