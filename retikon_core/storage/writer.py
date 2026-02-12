from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from typing import Iterable, Mapping
from urllib.parse import urlparse

import fsspec
import pyarrow as pa
import pyarrow.parquet as pq


@dataclass(frozen=True)
class WriteResult:
    uri: str
    rows: int
    bytes_written: int
    sha256: str


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_local(src_path: str, dest_path: str) -> None:
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    os.replace(src_path, dest_path)


def _write_remote(src_path: str, dest_uri: str) -> None:
    fs, path = fsspec.core.url_to_fs(dest_uri)
    fs.makedirs(os.path.dirname(path), exist_ok=True)
    with fs.open(path, "wb") as handle, open(src_path, "rb") as src:
        shutil.copyfileobj(src, handle)


def write_parquet(
    rows: Iterable[Mapping[str, object]],
    schema: pa.Schema,
    dest_uri: str,
    compression: str = "zstd",
    row_group_size: int | None = None,
) -> WriteResult:
    rows_list = rows if isinstance(rows, list) else list(rows)
    table = pa.Table.from_pylist(rows_list, schema=schema)
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        pq.write_table(
            table,
            tmp_path,
            compression=compression,
            row_group_size=row_group_size,
        )
        bytes_written = os.path.getsize(tmp_path)
        checksum = _sha256_file(tmp_path)
        parsed = urlparse(dest_uri)
        if parsed.scheme == "file":
            _write_local(tmp_path, parsed.path)
        elif parsed.scheme and parsed.netloc:
            _write_remote(tmp_path, dest_uri)
        else:
            _write_local(tmp_path, dest_uri)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return WriteResult(
        uri=dest_uri,
        rows=table.num_rows,
        bytes_written=bytes_written,
        sha256=checksum,
    )
