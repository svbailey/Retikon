from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlparse

import fsspec
import pyarrow as pa
import pyarrow.parquet as pq


@dataclass(frozen=True)
class ParquetWriteResult:
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


def _open_uri(uri: str):
    fs, path = fsspec.core.url_to_fs(uri)
    return fs, path


def _read_schema(uri: str) -> pa.Schema:
    fs, path = _open_uri(uri)
    with fs.open(path, "rb") as handle:
        return pq.read_schema(handle)


def _align_table(table: pa.Table, schema: pa.Schema) -> pa.Table:
    names = set(table.schema.names)
    for field in schema:
        if field.name not in names:
            table = table.append_column(
                field.name,
                pa.nulls(table.num_rows, type=field.type),
            )
    table = table.select(schema.names)
    return table.cast(schema, safe=False)


def unify_schema(uris: Iterable[str]) -> pa.Schema:
    schemas = [_read_schema(uri) for uri in uris]
    if not schemas:
        raise ValueError("No schemas available for compaction")
    return pa.unify_schemas(schemas)


def iter_tables(uris: Iterable[str], schema: pa.Schema) -> Iterable[pa.Table]:
    for uri in uris:
        fs, path = _open_uri(uri)
        with fs.open(path, "rb") as handle:
            parquet = pq.ParquetFile(handle)
            for idx in range(parquet.num_row_groups):
                table = parquet.read_row_group(idx)
                yield _align_table(table, schema)


def write_parquet_tables(
    *,
    tables: Iterable[pa.Table],
    schema: pa.Schema,
    dest_uri: str,
    compression: str = "zstd",
) -> ParquetWriteResult:
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        tmp_path = tmp.name

    rows = 0
    try:
        writer = pq.ParquetWriter(tmp_path, schema, compression=compression)
        try:
            for table in tables:
                writer.write_table(table)
                rows += table.num_rows
        finally:
            writer.close()

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

    return ParquetWriteResult(
        uri=dest_uri,
        rows=rows,
        bytes_written=bytes_written,
        sha256=checksum,
    )


def delete_uri(uri: str) -> None:
    fs, path = _open_uri(uri)
    fs.rm(path, recursive=False)


def uri_modified_at(uri: str) -> datetime | None:
    fs, path = _open_uri(uri)
    try:
        info = fs.info(path)
    except FileNotFoundError:
        return None
    updated = info.get("updated") or info.get("mtime")
    if isinstance(updated, datetime):
        return updated.astimezone(timezone.utc)
    if isinstance(updated, (int, float)):
        return datetime.fromtimestamp(updated, tz=timezone.utc)
    if isinstance(updated, str):
        try:
            return datetime.fromisoformat(updated.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
