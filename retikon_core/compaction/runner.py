from __future__ import annotations

import json
import os
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlparse

import fsspec

from retikon_core.audit import CompactionAuditRecord, write_compaction_audit_log
from retikon_core.compaction.io import (
    delete_uri,
    iter_tables,
    unify_schema,
    uri_modified_at,
    write_parquet_tables,
)
from retikon_core.compaction.policy import CompactionPolicy
from retikon_core.compaction.types import (
    CompactionBatch,
    CompactionGroup,
    CompactionOutput,
    CompactionReport,
    ManifestFile,
    ManifestInfo,
)
from retikon_core.logging import configure_logging, get_logger
from retikon_core.retention import RetentionPolicy
from retikon_core.storage import build_manifest, manifest_uri, write_manifest
from retikon_core.storage.paths import (
    GraphPaths,
    backend_scheme,
    graph_root,
    has_uri_scheme,
    join_uri,
    normalize_bucket_uri,
)
from retikon_core.storage.writer import WriteResult

SERVICE_NAME = "retikon-compaction"
logger = get_logger(__name__)


@dataclass(frozen=True)
class CompactionResult:
    outputs: list[CompactionOutput]
    removed_sources: list[str]
    audit_records: list[CompactionAuditRecord]
    counts: dict[str, int]


def _glob_files(pattern: str) -> list[str]:
    fs, path = fsspec.core.url_to_fs(pattern)
    matches = sorted(fs.glob(path))
    protocol = fs.protocol[0] if isinstance(fs.protocol, tuple) else fs.protocol
    if protocol in {"file", "local"}:
        return matches
    return [f"{protocol}://{match}" for match in matches]


def _read_manifest(uri: str) -> dict[str, object]:
    fs, path = fsspec.core.url_to_fs(uri)
    with fs.open(path, "rb") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _run_id_from_manifest_uri(uri: str) -> str:
    parsed = urlparse(uri)
    path = parsed.path if parsed.scheme else uri
    parts = path.strip("/").split("/")
    if "manifests" in parts:
        idx = parts.index("manifests")
        if len(parts) > idx + 1:
            return parts[idx + 1]
    return "unknown"


def _parse_graph_uri(uri: str) -> tuple[bool, str, str] | None:
    parsed = urlparse(uri)
    path = parsed.path if parsed.scheme else uri
    parts = path.strip("/").split("/")
    if "vertices" in parts:
        idx = parts.index("vertices")
        if len(parts) > idx + 2:
            return False, parts[idx + 1], parts[idx + 2]
    if "edges" in parts:
        idx = parts.index("edges")
        if len(parts) > idx + 2:
            return True, parts[idx + 1], parts[idx + 2]
    return None


def load_manifests(base_uri: str) -> list[ManifestInfo]:
    manifest_glob = join_uri(base_uri, "manifests", "*", "manifest.json")
    manifest_uris = _glob_files(manifest_glob)
    manifests: list[ManifestInfo] = []
    for manifest_path in manifest_uris:
        data = _read_manifest(manifest_path)
        files: list[ManifestFile] = []
        files_raw = data.get("files")
        if isinstance(files_raw, list):
            for item in files_raw:
                if not isinstance(item, dict):
                    continue
                uri = item.get("uri")
                if not uri:
                    continue
                files.append(
                    ManifestFile(
                        uri=str(uri),
                        rows=int(item.get("rows", 0)),
                        bytes_written=int(item.get("bytes_written", 0)),
                        sha256=str(item.get("sha256", "")),
                    )
                )
        counts_raw = data.get("counts")
        counts: dict[str, int] = {}
        if isinstance(counts_raw, dict):
            for key, value in counts_raw.items():
                try:
                    counts[str(key)] = int(value)
                except (TypeError, ValueError):
                    continue
        manifests.append(
            ManifestInfo(
                uri=manifest_path,
                run_id=_run_id_from_manifest_uri(manifest_path),
                pipeline_version=str(data.get("pipeline_version") or ""),
                schema_version=str(data.get("schema_version") or ""),
                counts=counts,
                files=files,
            )
        )
    return manifests


def _group_manifests(manifests: Iterable[ManifestInfo]) -> list[CompactionGroup]:
    groups: dict[tuple[str, bool, str], dict[str, ManifestFile]] = {}
    meta: dict[tuple[str, bool, str], tuple[str, str]] = {}

    for manifest in manifests:
        for file_entry in manifest.files:
            parsed = _parse_graph_uri(file_entry.uri)
            if not parsed:
                continue
            is_edge, entity_type, file_kind = parsed
            key = (entity_type, is_edge, manifest.run_id)
            groups.setdefault(key, {})[file_kind] = file_entry
            meta.setdefault(key, (manifest.pipeline_version, manifest.schema_version))

    output: list[CompactionGroup] = []
    for (entity_type, is_edge, run_id), files in groups.items():
        pipeline_version, schema_version = meta.get(
            (entity_type, is_edge, run_id),
            ("", ""),
        )
        output.append(
            CompactionGroup(
                entity_type=entity_type,
                is_edge=is_edge,
                run_id=run_id,
                pipeline_version=pipeline_version,
                schema_version=schema_version,
                files=files,
            )
        )
    return output


def _expected_kinds(groups: Iterable[CompactionGroup]) -> list[str]:
    kinds: set[str] = set()
    for group in groups:
        kinds.update(group.file_kinds())
    return sorted(kinds)


def _compact_batch(
    *,
    batch: CompactionBatch,
    base_uri: str,
    run_id: str,
    delete_source: bool,
    retention_policy: RetentionPolicy,
    retention_apply: bool,
    dry_run: bool,
    strict: bool,
) -> tuple[list[CompactionOutput], list[str], list[CompactionAuditRecord]]:
    outputs: list[CompactionOutput] = []
    removed: list[str] = []
    audit_records: list[CompactionAuditRecord] = []
    paths = GraphPaths(base_uri=base_uri)

    for file_kind in batch.file_kinds:
        source_files = [group.files[file_kind] for group in batch.groups]
        source_uris = [item.uri for item in source_files]
        source_rows = sum(item.rows for item in source_files)
        source_bytes = sum(item.bytes_written for item in source_files)
        retention_actions: list[dict[str, object]] = []
        for uri in source_uris:
            modified_at = uri_modified_at(uri)
            if modified_at is None:
                continue
            age_days = (
                datetime.now(timezone.utc) - modified_at
            ).total_seconds() / 86400.0
            tier = retention_policy.tier_for_age(age_days)
            action = (
                "delete"
                if tier == "delete"
                else "tier"
                if tier != "hot"
                else "keep"
            )
            retention_actions.append(
                {
                    "uri": uri,
                    "age_days": round(age_days, 2),
                    "tier": tier,
                    "action": action,
                }
            )
            if (
                retention_apply
                and tier == "delete"
                and not dry_run
                and not delete_source
            ):
                delete_uri(uri)
                removed.append(uri)

        if batch.is_edge:
            dest_uri = paths.edge(batch.entity_type, str(uuid.uuid4()))
        else:
            dest_uri = paths.vertex(batch.entity_type, file_kind, str(uuid.uuid4()))

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
                f"Row count mismatch for {batch.entity_type} {file_kind}: "
                f"{source_rows} -> {result.rows}"
            )

        outputs.append(
            CompactionOutput(
                entity_type=batch.entity_type,
                is_edge=batch.is_edge,
                file_kind=file_kind,
                result=result,
            )
        )

        if delete_source and not dry_run:
            for uri in source_uris:
                delete_uri(uri)
                removed.append(uri)

        audit_records.append(
            CompactionAuditRecord(
                run_id=run_id,
                entity_type=batch.entity_type,
                is_edge=batch.is_edge,
                file_kinds=[file_kind],
                source_files=[
                    {
                        "uri": item.uri,
                        "rows": item.rows,
                        "bytes_written": item.bytes_written,
                        "sha256": item.sha256,
                    }
                    for item in source_files
                ],
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
                started_at=datetime.now(timezone.utc).isoformat(),
                completed_at=datetime.now(timezone.utc).isoformat(),
                retention_actions=retention_actions or None,
            )
        )

    return outputs, removed, audit_records


def _schema_version_for(groups: Iterable[CompactionGroup]) -> str:
    versions = {group.schema_version for group in groups if group.schema_version}
    if not versions:
        return ""
    if len(versions) == 1:
        return versions.pop()
    return "mixed"


def run_compaction(
    *,
    base_uri: str,
    policy: CompactionPolicy | None = None,
    retention_policy: RetentionPolicy | None = None,
    pipeline_version: str | None = None,
    delete_source: bool = False,
    retention_apply: bool = False,
    dry_run: bool = False,
    strict: bool = True,
) -> CompactionReport:
    policy = policy or CompactionPolicy.from_env()
    retention_policy = retention_policy or RetentionPolicy.from_env()
    raw_pipeline = pipeline_version if pipeline_version is not None else os.getenv(
        "COMPACTION_PIPELINE_VERSION"
    )
    pipeline_version = raw_pipeline or "compaction"

    configure_logging(
        service=SERVICE_NAME,
        env=os.getenv("ENV"),
        version=os.getenv("RETIKON_VERSION"),
    )

    started = datetime.now(timezone.utc)
    start_time = time.monotonic()
    run_id = f"compaction-{started.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4()}"

    manifests = load_manifests(base_uri)
    if not manifests:
        completed = datetime.now(timezone.utc)
        return CompactionReport(
            run_id=run_id,
            manifest_uri=None,
            audit_uri=None,
            outputs=(),
            removed_sources=(),
            counts={},
            started_at=started.isoformat(),
            completed_at=completed.isoformat(),
            duration_seconds=0.0,
        )

    groups = _group_manifests(manifests)
    grouped: dict[tuple[str, bool], list[CompactionGroup]] = defaultdict(list)
    for group in groups:
        grouped[(group.entity_type, group.is_edge)].append(group)

    outputs: list[CompactionOutput] = []
    removed_sources: list[str] = []
    audit_records: list[CompactionAuditRecord] = []
    counts: dict[str, int] = defaultdict(int)

    for (entity_type, is_edge), entity_groups in grouped.items():
        kinds = _expected_kinds(entity_groups)
        if not kinds:
            continue
        if not is_edge and "core" not in kinds:
            logger.warning(
                "Skipping compaction with no core file",
                extra={"entity": entity_type},
            )
            continue
        eligible = [
            group for group in entity_groups if set(kinds).issubset(group.file_kinds())
        ]
        if not eligible:
            logger.warning(
                "No eligible groups for compaction",
                extra={"entity": entity_type, "kinds": kinds},
            )
            continue

        eligible.sort(key=lambda item: item.run_id)
        batches = policy.plan(groups=eligible, file_kinds=kinds)
        schema_version = _schema_version_for(eligible)

        for batch in batches:
            batch_outputs, removed, batch_audit = _compact_batch(
                batch=batch,
                base_uri=base_uri,
                run_id=run_id,
                delete_source=delete_source,
                retention_policy=retention_policy,
                retention_apply=retention_apply,
                dry_run=dry_run,
                strict=strict,
            )
            outputs.extend(batch_outputs)
            removed_sources.extend(removed)
            audit_records.extend(batch_audit)

            rows_by_kind = batch.rows_by_kind()
            if is_edge:
                counts[entity_type] += rows_by_kind.get("adj_list", 0)
            else:
                counts[entity_type] += rows_by_kind.get("core", 0)

        logger.info(
            "Compaction batches complete",
            extra={
                "entity": entity_type,
                "batches": len(batches),
                "schema_version": schema_version,
            },
        )

    completed = datetime.now(timezone.utc)
    duration = time.monotonic() - start_time
    manifest_path = None
    audit_uri = None

    if outputs and not dry_run:
        manifest = build_manifest(
            pipeline_version=pipeline_version,
            schema_version=_schema_version_for(groups),
            counts=dict(counts),
            files=[output.result for output in outputs],
            started_at=started,
            completed_at=completed,
        )
        manifest_path = manifest_uri(base_uri, run_id)
        write_manifest(manifest, manifest_path)

    if audit_records:
        audit_uri = write_compaction_audit_log(
            base_uri=base_uri,
            run_id=run_id,
            records=audit_records,
        )

    return CompactionReport(
        run_id=run_id,
        manifest_uri=manifest_path,
        audit_uri=audit_uri,
        outputs=tuple(outputs),
        removed_sources=tuple(removed_sources),
        counts=dict(counts),
        started_at=started.isoformat(),
        completed_at=completed.isoformat(),
        duration_seconds=duration,
    )


def main() -> None:
    graph_uri = os.getenv("GRAPH_URI")
    if not graph_uri:
        graph_bucket = os.getenv("GRAPH_BUCKET")
        graph_prefix = os.getenv("GRAPH_PREFIX", "")
        if graph_bucket:
            storage_backend = os.getenv("STORAGE_BACKEND", "local").strip().lower()
            scheme = backend_scheme(storage_backend)
            if scheme is None and not has_uri_scheme(graph_bucket):
                raise ValueError(
                    "GRAPH_BUCKET must include a URI scheme when STORAGE_BACKEND="
                    f"{storage_backend} (example: s3://bucket)"
                )
            graph_uri = graph_root(
                normalize_bucket_uri(graph_bucket, scheme=scheme),
                graph_prefix,
            )
        else:
            local_root = os.getenv("LOCAL_GRAPH_ROOT")
            if not local_root:
                raise ValueError("GRAPH_URI or GRAPH_BUCKET is required")
            graph_uri = local_root

    report = run_compaction(
        base_uri=graph_uri,
        delete_source=os.getenv("COMPACTION_DELETE_SOURCE", "0") == "1",
        retention_apply=os.getenv("RETENTION_APPLY", "0") == "1",
        dry_run=os.getenv("COMPACTION_DRY_RUN", "0") == "1",
        strict=os.getenv("COMPACTION_STRICT", "1") == "1",
    )
    logger.info(
        "Compaction completed",
        extra={
            "run_id": report.run_id,
            "outputs": len(report.outputs),
            "manifest_uri": report.manifest_uri,
            "audit_uri": report.audit_uri,
            "duration_seconds": report.duration_seconds,
        },
    )


if __name__ == "__main__":
    main()
