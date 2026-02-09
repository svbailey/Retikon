from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import urlparse

import fsspec


@dataclass(frozen=True)
class ManifestEntry:
    uri: str
    run_id: str
    completed_at: datetime
    is_compaction: bool
    files: tuple[str, ...]


@dataclass(frozen=True)
class GCPlan:
    graph_root: str
    keep_manifests: tuple[ManifestEntry, ...]
    keep_files: frozenset[str]
    candidate_files: tuple[str, ...]
    total_candidates: int
    total_candidates_bytes: int | None


def _parse_iso(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = f"{ts[:-1]}+00:00"
    return datetime.fromisoformat(ts).astimezone(timezone.utc)


def _normalize_graph_root(graph_root: str) -> str:
    return graph_root.rstrip("/")


def _root_from_env(graph_bucket: str, graph_prefix: str) -> str:
    bucket = graph_bucket.rstrip("/")
    prefix = graph_prefix.strip("/")
    if bucket.startswith("gs://") or bucket.startswith("s3://"):
        return f"{bucket.rstrip('/')}/{prefix}"
    return f"gs://{bucket}/{prefix}"


def _resolve_fs(graph_root: str) -> tuple[fsspec.AbstractFileSystem, str, str]:
    fs, path = fsspec.core.url_to_fs(graph_root)
    parsed = urlparse(graph_root)
    scheme = parsed.scheme
    if not scheme:
        scheme = fs.protocol[0] if isinstance(fs.protocol, (list, tuple)) else fs.protocol
    return fs, path.rstrip("/"), scheme


def _path_to_uri(scheme: str, path: str) -> str:
    return f"{scheme}://{path}"


def _load_manifest(
    *,
    fs: fsspec.AbstractFileSystem,
    scheme: str,
    manifest_path: str,
) -> ManifestEntry | None:
    try:
        with fs.open(manifest_path, "r") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    completed_at_raw = payload.get("completed_at") or payload.get("started_at")
    if completed_at_raw:
        completed_at = _parse_iso(completed_at_raw)
    else:
        completed_at = datetime.now(timezone.utc)
    run_id = manifest_path.rstrip("/").split("/")[-2]
    is_compaction = run_id.startswith("compaction-")
    files = tuple(item.get("uri") for item in payload.get("files", []) if item.get("uri"))
    return ManifestEntry(
        uri=_path_to_uri(scheme, manifest_path),
        run_id=run_id,
        completed_at=completed_at,
        is_compaction=is_compaction,
        files=files,
    )


def collect_manifests(graph_root: str) -> tuple[ManifestEntry, ...]:
    graph_root = _normalize_graph_root(graph_root)
    fs, root_path, scheme = _resolve_fs(graph_root)
    manifest_glob = f"{root_path}/manifests/*/manifest.json"
    manifest_paths = fs.glob(manifest_glob)
    manifests = []
    for path in manifest_paths:
        entry = _load_manifest(fs=fs, scheme=scheme, manifest_path=path)
        if entry:
            manifests.append(entry)
    manifests.sort(key=lambda entry: entry.completed_at)
    return tuple(manifests)


def build_gc_plan(
    *,
    graph_root: str,
    keep_recent_hours: int,
    keep_compaction: int,
    keep_latest: int,
    include_candidate_sizes: bool,
    exclude_prefixes: Iterable[str] | None = None,
) -> GCPlan:
    graph_root = _normalize_graph_root(graph_root)
    fs, root_path, scheme = _resolve_fs(graph_root)
    manifests = collect_manifests(graph_root)
    if not manifests:
        return GCPlan(
            graph_root=graph_root,
            keep_manifests=tuple(),
            keep_files=frozenset(),
            candidate_files=tuple(),
            total_candidates=0,
            total_candidates_bytes=0 if include_candidate_sizes else None,
        )

    now = datetime.now(timezone.utc)
    keep_set: list[ManifestEntry] = []
    if keep_recent_hours > 0:
        cutoff = now - timedelta(hours=keep_recent_hours)
        keep_set.extend([m for m in manifests if m.completed_at >= cutoff])

    compactions = [m for m in manifests if m.is_compaction]
    compactions.sort(key=lambda m: m.completed_at, reverse=True)
    if keep_compaction > 0:
        keep_set.extend(compactions[:keep_compaction])

    if keep_latest > 0:
        keep_set.extend(sorted(manifests, key=lambda m: m.completed_at, reverse=True)[:keep_latest])

    keep_unique = {}
    for entry in keep_set:
        keep_unique[entry.uri] = entry

    keep_files = set()
    for entry in keep_unique.values():
        keep_files.update(entry.files)

    healthcheck_path = f"{root_path}/healthcheck.parquet"
    if fs.exists(healthcheck_path):
        keep_files.add(_path_to_uri(scheme, healthcheck_path))

    exclude_prefixes = tuple(prefix.strip("/") for prefix in (exclude_prefixes or ()))
    parquet_paths = fs.glob(f"{root_path}/**/*.parquet")
    candidates: list[str] = []
    for path in parquet_paths:
        if exclude_prefixes and any(
            path.startswith(f"{root_path}/{prefix}") for prefix in exclude_prefixes
        ):
            continue
        uri = _path_to_uri(scheme, path)
        if uri in keep_files:
            continue
        candidates.append(uri)

    total_bytes = None
    if include_candidate_sizes:
        total = 0
        for uri in candidates:
            _, info_path = fsspec.core.url_to_fs(uri)
            try:
                total += fs.info(info_path).get("size", 0)
            except Exception:
                continue
        total_bytes = total

    return GCPlan(
        graph_root=graph_root,
        keep_manifests=tuple(keep_unique.values()),
        keep_files=frozenset(keep_files),
        candidate_files=tuple(candidates),
        total_candidates=len(candidates),
        total_candidates_bytes=total_bytes,
    )


def execute_gc(
    *,
    plan: GCPlan,
    dry_run: bool,
    batch_size: int = 1000,
) -> int:
    if dry_run or not plan.candidate_files:
        return 0
    fs, _, _ = _resolve_fs(plan.graph_root)
    deleted = 0
    batch: list[str] = []
    for uri in plan.candidate_files:
        batch.append(uri)
        if len(batch) >= batch_size:
            fs.rm(batch)
            deleted += len(batch)
            batch = []
    if batch:
        fs.rm(batch)
        deleted += len(batch)
    return deleted
