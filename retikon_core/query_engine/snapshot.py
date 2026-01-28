from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import fsspec

from retikon_core.errors import RecoverableError
from retikon_core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class SnapshotInfo:
    local_path: str
    metadata: dict[str, Any] | None


def _sidecar_uri(snapshot_uri: str) -> str:
    if snapshot_uri.endswith(".duckdb"):
        return f"{snapshot_uri}.json"
    return f"{snapshot_uri}.json"


def _download_remote(uri: str, dest: Path) -> None:
    fs, path = fsspec.core.url_to_fs(uri)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        fs.info(path)
    except FileNotFoundError as exc:
        raise RecoverableError(f"Snapshot file not found: {uri}") from exc
    except Exception as exc:
        raise RecoverableError(f"Failed to stat {uri}: {exc}") from exc
    try:
        with fs.open(path, "rb") as reader, open(dest, "wb") as writer:
            shutil.copyfileobj(reader, writer)
    except Exception as exc:
        raise RecoverableError(f"Failed to download {uri}: {exc}") from exc


def _read_local_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def download_snapshot(snapshot_uri: str, dest_dir: str = "/tmp") -> SnapshotInfo:
    if not snapshot_uri:
        raise ValueError("SNAPSHOT_URI is required")

    dest_dir_path = Path(dest_dir)
    dest_dir_path.mkdir(parents=True, exist_ok=True)

    parsed = urlparse(snapshot_uri)
    is_local = parsed.scheme in {"", "file"}
    if is_local:
        if parsed.scheme == "file":
            snapshot_path = Path(parsed.path)
        else:
            snapshot_path = Path(snapshot_uri)
    else:
        snapshot_path = None

    if is_local:
        if not snapshot_path.exists():  # type: ignore[union-attr]
            raise RecoverableError(f"Snapshot file not found: {snapshot_path}")

        local_path = dest_dir_path / snapshot_path.name  # type: ignore[union-attr]
        if snapshot_path.resolve() != local_path.resolve():  # type: ignore[union-attr]
            shutil.copy2(snapshot_path, local_path)

        sidecar_path = Path(f"{snapshot_path}.json")
        meta = _read_local_json(sidecar_path)
    else:
        filename = Path(parsed.path).name if parsed.path else "snapshot.duckdb"
        local_path = dest_dir_path / filename
        _download_remote(snapshot_uri, local_path)
        sidecar = _sidecar_uri(snapshot_uri)
        meta = None
        try:
            sidecar_path = dest_dir_path / Path(urlparse(sidecar).path).name
            _download_remote(sidecar, sidecar_path)
            meta = _read_local_json(sidecar_path)
        except RecoverableError:
            meta = None

    logger.info(
        "Snapshot prepared",
        extra={"snapshot_path": str(local_path)},
    )

    return SnapshotInfo(local_path=str(local_path), metadata=meta)
