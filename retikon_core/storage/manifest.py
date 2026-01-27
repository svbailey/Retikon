from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlparse

import fsspec

from retikon_core.storage.object_store import ObjectStore, atomic_write_bytes
from retikon_core.storage.writer import WriteResult


@dataclass(frozen=True)
class ManifestFile:
    uri: str
    rows: int
    bytes_written: int
    sha256: str


def build_manifest(
    pipeline_version: str,
    schema_version: str,
    counts: dict[str, int],
    files: Iterable[WriteResult],
    started_at: datetime,
    completed_at: datetime,
) -> dict[str, object]:
    manifest_files = [
        ManifestFile(
            uri=item.uri,
            rows=item.rows,
            bytes_written=item.bytes_written,
            sha256=item.sha256,
        )
        for item in files
    ]
    return {
        "pipeline_version": pipeline_version,
        "schema_version": schema_version,
        "started_at": started_at.astimezone(timezone.utc).isoformat(),
        "completed_at": completed_at.astimezone(timezone.utc).isoformat(),
        "counts": counts,
        "files": [asdict(item) for item in manifest_files],
    }


def write_manifest(manifest: dict[str, object], dest_uri: str) -> None:
    payload = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
    parsed = urlparse(dest_uri)
    if parsed.scheme == "file" or not parsed.scheme:
        store = ObjectStore.from_base_uri(dest_uri)
        atomic_write_bytes(store.base_path, payload)
        return
    fs, path = fsspec.core.url_to_fs(dest_uri)
    fs.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
    with fs.open(path, "wb") as handle:
        handle.write(payload)
