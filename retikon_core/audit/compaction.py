from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable

import fsspec

from retikon_core.storage.paths import join_uri


@dataclass(frozen=True)
class CompactionAuditRecord:
    run_id: str
    entity_type: str
    is_edge: bool
    file_kinds: list[str]
    source_files: list[dict[str, object]]
    output_files: list[dict[str, object]]
    rows_in: int
    rows_out: int
    bytes_in: int
    bytes_out: int
    status: str
    started_at: str
    completed_at: str
    error: str | None = None
    retention_actions: list[dict[str, object]] | None = None


def write_compaction_audit_log(
    *,
    base_uri: str,
    run_id: str,
    records: Iterable[CompactionAuditRecord],
) -> str:
    now = datetime.now(timezone.utc).isoformat()
    dest_uri = join_uri(base_uri, "audit", "compaction", f"{run_id}.jsonl")
    fs, path = fsspec.core.url_to_fs(dest_uri)
    fs.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
    with fs.open(path, "wb") as handle:
        header = {"run_id": run_id, "written_at": now}
        handle.write((json.dumps(header) + "\n").encode("utf-8"))
        for record in records:
            handle.write((json.dumps(asdict(record)) + "\n").encode("utf-8"))
    return dest_uri
