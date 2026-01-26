from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from google.cloud import storage

from retikon_core.errors import RecoverableError
from retikon_core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class SnapshotInfo:
    local_path: str
    metadata: dict[str, Any] | None


def _parse_gcs_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "gs" or not parsed.netloc:
        raise ValueError(f"Unsupported GCS URI: {uri}")
    bucket = parsed.netloc
    path = parsed.path.lstrip("/")
    if not path:
        raise ValueError(f"Missing object path in GCS URI: {uri}")
    return bucket, path


def _sidecar_uri(snapshot_uri: str) -> str:
    if snapshot_uri.endswith(".duckdb"):
        return f"{snapshot_uri}.json"
    return f"{snapshot_uri}.json"


def _download_gcs_blob(bucket: str, object_name: str, dest: Path) -> None:
    client = storage.Client()
    blob = client.bucket(bucket).blob(object_name)
    if not blob.exists():
        raise RecoverableError(f"GCS object not found: gs://{bucket}/{object_name}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(dest)


def _read_local_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def download_snapshot(snapshot_uri: str, dest_dir: str = "/tmp") -> SnapshotInfo:
    if not snapshot_uri:
        raise ValueError("SNAPSHOT_URI is required")

    dest_dir_path = Path(dest_dir)
    dest_dir_path.mkdir(parents=True, exist_ok=True)

    if snapshot_uri.startswith("gs://"):
        bucket, object_name = _parse_gcs_uri(snapshot_uri)
        filename = Path(object_name).name
        local_path = dest_dir_path / filename
        _download_gcs_blob(bucket, object_name, local_path)

        sidecar = _sidecar_uri(snapshot_uri)
        meta: dict[str, Any] | None = None
        try:
            sidecar_bucket, sidecar_obj = _parse_gcs_uri(sidecar)
            sidecar_path = dest_dir_path / Path(sidecar_obj).name
            _download_gcs_blob(sidecar_bucket, sidecar_obj, sidecar_path)
            meta = _read_local_json(sidecar_path)
        except RecoverableError:
            meta = None

        return SnapshotInfo(local_path=str(local_path), metadata=meta)

    parsed = urlparse(snapshot_uri)
    if parsed.scheme == "file":
        snapshot_path = Path(parsed.path)
    else:
        snapshot_path = Path(snapshot_uri)

    if not snapshot_path.exists():
        raise RecoverableError(f"Snapshot file not found: {snapshot_path}")

    local_path = dest_dir_path / snapshot_path.name
    if snapshot_path.resolve() != local_path.resolve():
        shutil.copy2(snapshot_path, local_path)

    sidecar_path = Path(f"{snapshot_path}.json")
    meta = _read_local_json(sidecar_path)

    logger.info(
        "Snapshot prepared",
        extra={"snapshot_path": str(local_path)},
    )

    return SnapshotInfo(local_path=str(local_path), metadata=meta)
