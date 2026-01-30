from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Any

import fsspec

from retikon_core.errors import PermanentError, RecoverableError


@dataclass(frozen=True)
class DownloadResult:
    path: str
    size_bytes: int
    content_type: str | None
    md5_hash: str | None
    crc32c: str | None
    metadata: dict[str, str] | None = None


def _info_for_uri(fs: fsspec.AbstractFileSystem, path: str) -> dict[str, Any]:
    try:
        return fs.info(path)
    except FileNotFoundError as exc:
        raise PermanentError(f"Object not found: {path}") from exc
    except Exception as exc:
        raise RecoverableError(f"Failed to stat {path}: {exc}") from exc


def _extract_metadata(
    info: dict[str, Any],
) -> tuple[str | None, str | None, str | None, dict[str, str] | None, int | None]:
    size = info.get("size") or info.get("Size")
    content_type = info.get("content_type") or info.get("ContentType") or info.get(
        "contentType"
    )
    md5_hash = info.get("md5") or info.get("md5Hash")
    crc32c = info.get("crc32c")
    metadata = info.get("metadata") or info.get("Metadata")
    if isinstance(metadata, dict):
        metadata = {str(k): str(v) for k, v in metadata.items()}
    else:
        metadata = None
    return (
        content_type,
        md5_hash,
        crc32c,
        metadata,
        size if size is not None else None,
    )


def download_to_tmp(
    uri: str,
    max_bytes: int,
) -> DownloadResult:
    fs, path = fsspec.core.url_to_fs(uri)
    info = _info_for_uri(fs, path)
    content_type, md5_hash, crc32c, metadata, size_hint = _extract_metadata(info)
    if size_hint is not None and size_hint > max_bytes:
        raise PermanentError(f"Object too large: {size_hint} bytes")

    tmp_handle = tempfile.NamedTemporaryFile(delete=False)
    tmp_path = tmp_handle.name
    tmp_handle.close()

    try:
        size = 0
        with fs.open(path, "rb") as reader, open(tmp_path, "wb") as writer:
            while True:
                chunk = reader.read(8 * 1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise PermanentError("Download exceeded MAX_RAW_BYTES")
                writer.write(chunk)
    except Exception as exc:
        cleanup_tmp(tmp_path)
        if isinstance(exc, PermanentError):
            raise
        raise RecoverableError(f"Failed downloading {uri}: {exc}") from exc

    return DownloadResult(
        path=tmp_path,
        size_bytes=size,
        content_type=content_type,
        md5_hash=md5_hash,
        crc32c=crc32c,
        metadata=metadata,
    )


def cleanup_tmp(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        return
