from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable

import fsspec
import pyarrow.parquet as pq

from retikon_core.storage.paths import join_uri, vertex_part_uri
from retikon_core.storage.schemas import schema_for
from retikon_core.storage.writer import WriteResult, write_parquet


@dataclass(frozen=True)
class DatasetRecord:
    id: str
    name: str
    description: str | None
    org_id: str | None
    site_id: str | None
    stream_id: str | None
    tags: str | None
    size: int | None
    created_at: datetime
    updated_at: datetime
    pipeline_version: str
    schema_version: str


@dataclass(frozen=True)
class AnnotationRecord:
    id: str
    dataset_id: str
    media_asset_id: str
    label: str
    value: str | None
    annotator: str | None
    status: str
    qa_status: str | None
    org_id: str | None
    site_id: str | None
    stream_id: str | None
    created_at: datetime
    updated_at: datetime
    pipeline_version: str
    schema_version: str


def _dataset_uri(base_uri: str, part_id: str) -> str:
    return vertex_part_uri(base_uri, "Dataset", "core", part_id)


def _annotation_uri(base_uri: str, part_id: str) -> str:
    return vertex_part_uri(base_uri, "Annotation", "core", part_id)


def create_dataset(
    *,
    base_uri: str,
    name: str,
    description: str | None = None,
    org_id: str | None = None,
    site_id: str | None = None,
    stream_id: str | None = None,
    tags: Iterable[str] | None = None,
    size: int | None = None,
    pipeline_version: str = "dev",
    schema_version: str = "1",
) -> WriteResult:
    now = datetime.now(timezone.utc)
    record = DatasetRecord(
        id=str(uuid.uuid4()),
        name=name,
        description=description,
        org_id=org_id,
        site_id=site_id,
        stream_id=stream_id,
        tags=_join_tags(tags),
        size=size,
        created_at=now,
        updated_at=now,
        pipeline_version=pipeline_version,
        schema_version=schema_version,
    )
    schema = schema_for("Dataset", "core")
    dest_uri = _dataset_uri(base_uri, str(uuid.uuid4()))
    return write_parquet([asdict(record)], schema, dest_uri)


def add_annotation(
    *,
    base_uri: str,
    dataset_id: str,
    media_asset_id: str,
    label: str,
    value: str | None = None,
    annotator: str | None = None,
    status: str = "pending",
    qa_status: str | None = None,
    org_id: str | None = None,
    site_id: str | None = None,
    stream_id: str | None = None,
    pipeline_version: str = "dev",
    schema_version: str = "1",
) -> WriteResult:
    now = datetime.now(timezone.utc)
    record = AnnotationRecord(
        id=str(uuid.uuid4()),
        dataset_id=dataset_id,
        media_asset_id=media_asset_id,
        label=label,
        value=value,
        annotator=annotator,
        status=status,
        qa_status=qa_status,
        org_id=org_id,
        site_id=site_id,
        stream_id=stream_id,
        created_at=now,
        updated_at=now,
        pipeline_version=pipeline_version,
        schema_version=schema_version,
    )
    schema = schema_for("Annotation", "core")
    dest_uri = _annotation_uri(base_uri, str(uuid.uuid4()))
    return write_parquet([asdict(record)], schema, dest_uri)


def list_datasets(base_uri: str) -> list[dict[str, object]]:
    return _read_records(join_uri(base_uri, "vertices", "Dataset", "core", "*.parquet"))


def list_annotations(base_uri: str) -> list[dict[str, object]]:
    return _read_records(
        join_uri(base_uri, "vertices", "Annotation", "core", "*.parquet")
    )


def _read_records(uri_pattern: str) -> list[dict[str, object]]:
    fs, path = fsspec.core.url_to_fs(uri_pattern)
    matches = sorted(fs.glob(path))
    if not matches:
        return []
    rows: list[dict[str, object]] = []
    for match in matches:
        with fs.open(match, "rb") as handle:
            table = pq.read_table(handle)
        data = table.to_pylist()
        rows.extend(data)
    return rows


def _join_tags(tags: Iterable[str] | None) -> str | None:
    if not tags:
        return None
    cleaned = [str(tag).strip() for tag in tags if str(tag).strip()]
    if not cleaned:
        return None
    return ",".join(cleaned)
