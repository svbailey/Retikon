from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

try:
    from google.cloud import storage
except ImportError:  # pragma: no cover - optional dependency
    storage = None

from retikon_core.errors import PermanentError, RecoverableError


@dataclass(frozen=True)
class DownloadResult:
    path: str
    size_bytes: int
    content_type: str | None
    md5_hash: str | None
    crc32c: str | None
    metadata: dict[str, str] | None = None


def fetch_blob_metadata(
    client: "storage.Client", bucket: str, name: str
) -> "storage.Blob":
    if storage is None:
        raise PermanentError("google-cloud-storage is required for GCS downloads")
    blob = client.bucket(bucket).get_blob(name)
    if blob is None:
        raise PermanentError(f"Object not found: gs://{bucket}/{name}")
    return blob


def download_to_tmp(
    client: storage.Client,
    bucket: str,
    name: str,
    max_bytes: int,
) -> DownloadResult:
    blob = fetch_blob_metadata(client, bucket, name)
    if blob.size is not None and blob.size > max_bytes:
        raise PermanentError(f"Object too large: {blob.size} bytes")

    tmp_handle = tempfile.NamedTemporaryFile(delete=False)
    tmp_path = tmp_handle.name
    tmp_handle.close()

    try:
        size = 0
        with blob.open("rb") as reader, open(tmp_path, "wb") as writer:
            while True:
                chunk = reader.read(8 * 1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise PermanentError("Download exceeded MAX_RAW_BYTES")
                writer.write(chunk)
    except PermanentError:
        raise
    except Exception as exc:
        raise RecoverableError(
            f"Failed downloading gs://{bucket}/{name}: {exc}"
        ) from exc

    return DownloadResult(
        path=tmp_path,
        size_bytes=size,
        content_type=blob.content_type,
        md5_hash=blob.md5_hash,
        crc32c=blob.crc32c,
        metadata=blob.metadata or None,
    )


def cleanup_tmp(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        return
