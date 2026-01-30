from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import fsspec
import pyarrow.parquet as pq

from retikon_core.audit.compaction import (
    CompactionAuditRecord,
    write_compaction_audit_log,
)
from retikon_core.compaction.io import iter_tables, unify_schema, write_parquet_tables
from retikon_core.logging import get_logger
from retikon_core.storage.paths import join_uri, vertex_part_uri
from retikon_core.storage.writer import WriteResult

logger = get_logger(__name__)


@dataclass(frozen=True)
class AuditCompactionPolicy:
    target_min_bytes: int = 32 * 1024 * 1024
    target_max_bytes: int = 256 * 1024 * 1024
    max_files_per_batch: int = 500
    max_batches: int = 10
    min_age_seconds: int = 300

    @classmethod
    def from_env(cls) -> "AuditCompactionPolicy":
        def _env_int(name: str, default: int) -> int:
            raw = os.getenv(name)
            if not raw:
                return default
            try:
                return int(raw)
            except ValueError as exc:
                raise ValueError(f"{name} must be an integer") from exc

        return cls(
            target_min_bytes=_env_int(
                "AUDIT_COMPACTION_TARGET_MIN_BYTES", cls.target_min_bytes
            ),
            target_max_bytes=_env_int(
                "AUDIT_COMPACTION_TARGET_MAX_BYTES", cls.target_max_bytes
            ),
            max_files_per_batch=_env_int(
                "AUDIT_COMPACTION_MAX_FILES_PER_BATCH",
                cls.max_files_per_batch,
            ),
            max_batches=_env_int(
                "AUDIT_COMPACTION_MAX_BATCHES", cls.max_batches
            ),
            min_age_seconds=_env_int(
                "AUDIT_COMPACTION_MIN_AGE_SECONDS",
                cls.min_age_seconds,
            ),
        )


@dataclass(frozen=True)
class AuditCompactionReport:
    run_id: str
    audit_uri: str | None
    source_files: int
    eligible_files: int
    skipped_recent: int
    batches: int
    outputs: int
    removed_sources: int
    errors: int
    started_at: str
    completed_at: str
    duration_seconds: float


@dataclass(frozen=True)
class _AuditFile:
    uri: str
    path: str
    size: int
    updated_at: datetime | None


def _info_timestamp(info: dict[str, object]) -> datetime | None:
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


def _glob_audit_files(uri_pattern: str) -> list[_AuditFile]:
    fs, path = fsspec.core.url_to_fs(uri_pattern)
    matches = sorted(fs.glob(path))
    protocol = fs.protocol[0] if isinstance(fs.protocol, tuple) else fs.protocol
    output: list[_AuditFile] = []
    for match in matches:
        info = fs.info(match)
        size = int(info.get("size", 0) or 0)
        updated_at = _info_timestamp(info)
        if protocol in {None, "file", "local"}:
            uri = match
        else:
            uri = f"{protocol}://{match}"
        output.append(
            _AuditFile(
                uri=uri,
                path=match,
                size=size,
                updated_at=updated_at,
            )
        )
    return output


def _parquet_rows(uri: str) -> int:
    fs, path = fsspec.core.url_to_fs(uri)
    with fs.open(path, "rb") as handle:
        parquet = pq.ParquetFile(handle)
        metadata = parquet.metadata
        return int(metadata.num_rows) if metadata else 0


def _audit_glob(base_uri: str) -> str:
    return join_uri(base_uri, "vertices", "AuditLog", "core", "*.parquet")


def _plan_batches(
    files: list[_AuditFile],
    policy: AuditCompactionPolicy,
) -> list[list[_AuditFile]]:
    if policy.max_batches <= 0:
        return []
    if policy.max_files_per_batch < 2:
        return []

    def _sort_key(item: _AuditFile) -> tuple[float, int]:
        if item.updated_at is None:
            return (0.0, item.size)
        return (item.updated_at.timestamp(), item.size)

    ordered = sorted(files, key=_sort_key)
    batches: list[list[_AuditFile]] = []
    current: list[_AuditFile] = []
    running_bytes = 0

    def flush(final: bool = False) -> None:
        nonlocal current, running_bytes
        if len(current) > 1:
            batches.append(current)
        current = []
        running_bytes = 0
        if final:
            return

    for item in ordered:
        projected = running_bytes + item.size
        if current and (
            projected > policy.target_max_bytes
            or len(current) >= policy.max_files_per_batch
        ):
            flush()
            if policy.max_batches and len(batches) >= policy.max_batches:
                return batches

        current.append(item)
        running_bytes += item.size

        if (
            running_bytes >= policy.target_min_bytes
            or len(current) >= policy.max_files_per_batch
        ):
            flush()
            if policy.max_batches and len(batches) >= policy.max_batches:
                return batches

    flush(final=True)
    return batches


def compact_audit_logs(
    *,
    base_uri: str,
    policy: AuditCompactionPolicy | None = None,
    delete_source: bool | None = None,
    dry_run: bool | None = None,
    strict: bool | None = None,
) -> AuditCompactionReport:
    policy = policy or AuditCompactionPolicy.from_env()
    delete_source = (
        delete_source
        if delete_source is not None
        else os.getenv("AUDIT_COMPACTION_DELETE_SOURCE", "0") == "1"
    )
    dry_run = (
        dry_run
        if dry_run is not None
        else os.getenv("AUDIT_COMPACTION_DRY_RUN", "0") == "1"
    )
    strict = (
        strict
        if strict is not None
        else os.getenv("AUDIT_COMPACTION_STRICT", "1") == "1"
    )

    started = datetime.now(timezone.utc)
    start_time = time.monotonic()
    run_id = f"audit-compaction-{started.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4()}"

    all_files = _glob_audit_files(_audit_glob(base_uri))
    now = datetime.now(timezone.utc)
    eligible: list[_AuditFile] = []
    skipped_recent = 0
    for item in all_files:
        if item.updated_at is None:
            eligible.append(item)
            continue
        age_seconds = (now - item.updated_at).total_seconds()
        if age_seconds < policy.min_age_seconds:
            skipped_recent += 1
            continue
        eligible.append(item)

    batches = _plan_batches(eligible, policy)
    outputs: list[WriteResult] = []
    removed: list[str] = []
    audit_records: list[CompactionAuditRecord] = []
    errors = 0

    for batch in batches:
        source_uris = [item.uri for item in batch]
        source_rows = 0
        source_bytes = sum(item.size for item in batch)
        source_files = []
        for item in batch:
            rows = _parquet_rows(item.uri)
            source_rows += rows
            source_files.append(
                {
                    "uri": item.uri,
                    "rows": rows,
                    "bytes_written": item.size,
                    "sha256": "",
                }
            )
        dest_uri = vertex_part_uri(base_uri, "AuditLog", "core", str(uuid.uuid4()))
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            if dry_run:
                result = WriteResult(
                    uri=dest_uri,
                    rows=source_rows,
                    bytes_written=source_bytes,
                    sha256="",
                )
            else:
                schema = unify_schema(source_uris)
                tables = iter_tables(source_uris, schema)
                write_result = write_parquet_tables(
                    tables=tables,
                    schema=schema,
                    dest_uri=dest_uri,
                )
                result = WriteResult(
                    uri=write_result.uri,
                    rows=write_result.rows,
                    bytes_written=write_result.bytes_written,
                    sha256=write_result.sha256,
                )

            if strict and result.rows != source_rows:
                raise ValueError(
                    f"Audit rows mismatch: {source_rows} -> {result.rows}"
                )

            outputs.append(result)
            if delete_source and not dry_run:
                for uri in source_uris:
                    fs, path = fsspec.core.url_to_fs(uri)
                    fs.rm(path, recursive=False)
                    removed.append(uri)

            audit_records.append(
                CompactionAuditRecord(
                    run_id=run_id,
                    entity_type="AuditLog",
                    is_edge=False,
                    file_kinds=["core"],
                    source_files=source_files,
                    output_files=[
                        {
                            "uri": result.uri,
                            "rows": result.rows,
                            "bytes_written": result.bytes_written,
                            "sha256": result.sha256,
                        }
                    ],
                    rows_in=source_rows,
                    rows_out=result.rows,
                    bytes_in=source_bytes,
                    bytes_out=result.bytes_written,
                    status="ok",
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
            )
        except Exception as exc:  # noqa: BLE001
            errors += 1
            logger.exception(
                "Audit compaction batch failed",
                extra={"run_id": run_id, "error": str(exc)},
            )
            audit_records.append(
                CompactionAuditRecord(
                    run_id=run_id,
                    entity_type="AuditLog",
                    is_edge=False,
                    file_kinds=["core"],
                    source_files=source_files,
                    output_files=[],
                    rows_in=source_rows,
                    rows_out=0,
                    bytes_in=source_bytes,
                    bytes_out=0,
                    status="error",
                    error=str(exc),
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
            )

    audit_uri = None
    if audit_records:
        audit_uri = write_compaction_audit_log(
            base_uri=base_uri,
            run_id=run_id,
            records=audit_records,
        )

    completed = datetime.now(timezone.utc)
    duration = time.monotonic() - start_time
    return AuditCompactionReport(
        run_id=run_id,
        audit_uri=audit_uri,
        source_files=len(all_files),
        eligible_files=len(eligible),
        skipped_recent=skipped_recent,
        batches=len(batches),
        outputs=len(outputs),
        removed_sources=len(removed),
        errors=errors,
        started_at=started.isoformat(),
        completed_at=completed.isoformat(),
        duration_seconds=duration,
    )
