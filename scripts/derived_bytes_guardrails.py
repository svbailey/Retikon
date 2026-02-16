#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import fsspec
from google.cloud import firestore

COMPONENT_KEYS = (
    "manifest_b",
    "parquet_b",
    "thumbnails_b",
    "frames_b",
    "transcript_b",
    "embeddings_b",
    "other_b",
)


def percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    values = sorted(values)
    if pct <= 0:
        return values[0]
    if pct >= 100:
        return values[-1]
    k = (len(values) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    d0 = values[f] * (c - k)
    d1 = values[c] * (k - f)
    return d0 + d1


def summarize(values: List[float]) -> Dict[str, Optional[float]]:
    return {
        "count": len(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
    }


def coerce_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _manifest_size_bytes(uri: str, cache: Dict[str, Optional[float]]) -> Optional[float]:
    if uri in cache:
        return cache[uri]
    try:
        fs, path = fsspec.core.url_to_fs(uri)
        info = fs.info(path)
        size = info.get("size")
        cache[uri] = float(size) if isinstance(size, (int, float)) else None
    except Exception:
        cache[uri] = None
    return cache[uri]


def fetch_docs(
    client: firestore.Client,
    *,
    collection: str,
    prefix: str,
) -> List[firestore.DocumentSnapshot]:
    upper = f"{prefix}\uf8ff"
    query = (
        client.collection(collection)
        .where(field_path="object_name", op_string=">=", value=prefix)
        .where(field_path="object_name", op_string="<=", value=upper)
    )
    return list(query.stream())


def _latest_run_id(
    client: firestore.Client,
    *,
    collection: str,
    raw_prefix: str,
    modality: str,
) -> Optional[str]:
    prefix = f"{raw_prefix}/{modality}/"
    upper = f"{prefix}\uf8ff"
    query = (
        client.collection(collection)
        .where(field_path="object_name", op_string=">=", value=prefix)
        .where(field_path="object_name", op_string="<=", value=upper)
        .order_by("object_name", direction=firestore.Query.DESCENDING)
        .limit(25)
    )
    for doc in query.stream():
        name = (doc.to_dict() or {}).get("object_name", "")
        if not isinstance(name, str) or not name.startswith(prefix):
            continue
        remainder = name[len(prefix) :]
        if "/" not in remainder:
            continue
        return remainder.split("/", 1)[0]
    return None


def _resolve_breakdown(io_payload: dict) -> dict[str, float]:
    breakdown: dict[str, float] = {}
    raw_breakdown = io_payload.get("derived_b_breakdown")
    if isinstance(raw_breakdown, dict):
        for key in COMPONENT_KEYS:
            val = coerce_float(raw_breakdown.get(key))
            if val is not None:
                breakdown[key] = val
    if breakdown:
        return breakdown
    parquet_b = coerce_float(io_payload.get("bytes_parquet"))
    thumb_b = coerce_float(io_payload.get("bytes_thumbnails"))
    manifest_b = coerce_float(io_payload.get("bytes_manifest"))
    if parquet_b is not None:
        breakdown["parquet_b"] = parquet_b
    if thumb_b is not None:
        breakdown["thumbnails_b"] = thumb_b
    if manifest_b is not None:
        breakdown["manifest_b"] = manifest_b
    return breakdown


def _resolved_components(
    payload: dict[str, Any],
    io_payload: dict[str, Any],
    *,
    manifest_size_cache: Dict[str, Optional[float]],
) -> Tuple[dict[str, float], Optional[float]]:
    breakdown = _resolve_breakdown(io_payload)
    manifest_uri = payload.get("manifest_uri")
    if "manifest_b" not in breakdown and isinstance(manifest_uri, str) and manifest_uri:
        manifest_b = _manifest_size_bytes(manifest_uri, manifest_size_cache)
        if manifest_b is not None:
            breakdown["manifest_b"] = manifest_b

    derived_total = coerce_float(io_payload.get("derived_b_total"))
    if derived_total is None:
        derived_total = coerce_float(io_payload.get("bytes_derived"))
    if derived_total is None and breakdown:
        derived_total = sum(
            value for key, value in breakdown.items() if key != "manifest_b"
        )

    if "other_b" not in breakdown and isinstance(derived_total, (int, float)):
        known = sum(
            breakdown.get(key, 0.0)
            for key in ("parquet_b", "thumbnails_b", "frames_b", "transcript_b", "embeddings_b")
        )
        residual = max(0.0, float(derived_total) - float(known))
        breakdown["other_b"] = residual

    return breakdown, derived_total


def collect_metrics(docs: Iterable[firestore.DocumentSnapshot]) -> dict[str, Any]:
    totals: List[float] = []
    per_component: Dict[str, List[float]] = {key: [] for key in COMPONENT_KEYS}
    manifest_size_cache: Dict[str, Optional[float]] = {}

    for doc in docs:
        payload = doc.to_dict() or {}
        metrics = payload.get("metrics") or {}
        pipeline = metrics.get("pipeline") or {}
        io_payload = pipeline.get("io") or {}

        breakdown, derived_total = _resolved_components(
            payload,
            io_payload,
            manifest_size_cache=manifest_size_cache,
        )
        if derived_total is None:
            continue
        totals.append(derived_total)

        for key in COMPONENT_KEYS:
            value = coerce_float(breakdown.get(key))
            if value is None:
                continue
            per_component[key].append(value)

    summary = {
        "derived_b_total": summarize(totals),
        "components": {key: summarize(values) for key, values in per_component.items()},
    }
    return summary


def _open_output(path: str):
    fs, fs_path = fsspec.core.url_to_fs(path)
    directory = os.path.dirname(fs_path)
    if directory:
        fs.makedirs(directory, exist_ok=True)
    return fs.open(fs_path, "w")


def _load_baseline(path: str) -> dict[str, float]:
    fs, fs_path = fsspec.core.url_to_fs(path)
    with fs.open(fs_path, "r") as handle:
        payload = json.load(handle)
    components = payload.get("components") or {}
    baseline: dict[str, float] = {}
    if isinstance(components, dict):
        for key, value in components.items():
            if isinstance(value, (int, float)):
                baseline[key] = float(value)
    total = payload.get("derived_b_total")
    if isinstance(total, (int, float)):
        baseline["derived_b_total"] = float(total)
    return baseline


def _write_baseline(path: str, summary: dict[str, Any]) -> None:
    components: dict[str, float] = {}
    for key, stats in (summary.get("components") or {}).items():
        if isinstance(stats, dict) and isinstance(stats.get("p95"), (int, float)):
            components[key] = float(stats["p95"])
    total = None
    total_stats = summary.get("derived_b_total")
    if isinstance(total_stats, dict) and isinstance(total_stats.get("p95"), (int, float)):
        total = float(total_stats["p95"])
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "components": components,
        "derived_b_total": total,
    }
    with _open_output(path) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute derived-bytes guardrails by component."
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--collection", default="ingestion_events")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--raw-prefix", required=True)
    parser.add_argument("--run-id", required=True, help="Run id or 'latest'")
    parser.add_argument(
        "--modalities",
        default="docs,images,audio,videos",
        help="Comma-separated modalities to include.",
    )
    parser.add_argument("--output", help="Optional JSON output path")
    parser.add_argument("--write-baseline", help="Write baseline JSON (p95) to path")
    parser.add_argument("--baseline", help="Baseline JSON to compare against")
    parser.add_argument("--multiplier", type=float, default=2.0)
    args = parser.parse_args()

    raw_prefix = args.raw_prefix.strip("/")
    modalities = [item.strip() for item in args.modalities.split(",") if item.strip()]
    client = firestore.Client(project=args.project)
    run_ids_by_modality: dict[str, str] = {}
    if args.run_id == "latest":
        for modality in modalities:
            run_id = _latest_run_id(
                client,
                collection=args.collection,
                raw_prefix=raw_prefix,
                modality=modality,
            )
            if run_id:
                run_ids_by_modality[modality] = run_id
    else:
        run_ids_by_modality = {modality: args.run_id for modality in modalities}

    docs: list[firestore.DocumentSnapshot] = []
    seen: set[str] = set()
    for modality in modalities:
        run_id = run_ids_by_modality.get(modality)
        if not run_id:
            continue
        prefix = f"{raw_prefix}/{modality}/{run_id}/"
        for doc in fetch_docs(client, collection=args.collection, prefix=prefix):
            if doc.id in seen:
                continue
            seen.add(doc.id)
            docs.append(doc)
    summary = collect_metrics(docs)
    summary["run_id"] = args.run_id
    summary["run_ids_by_modality"] = run_ids_by_modality
    summary["bucket"] = args.bucket
    summary["raw_prefix"] = args.raw_prefix

    payload = json.dumps(summary, indent=2, sort_keys=True)
    print(payload)

    if args.output:
        with _open_output(args.output) as handle:
            handle.write(payload)

    if args.write_baseline:
        _write_baseline(args.write_baseline, summary)

    if args.baseline:
        baseline = _load_baseline(args.baseline)
        violations = []
        total_stats = summary.get("derived_b_total") or {}
        total_p95 = total_stats.get("p95")
        if isinstance(total_p95, (int, float)) and "derived_b_total" in baseline:
            limit = baseline["derived_b_total"] * args.multiplier
            if total_p95 > limit:
                violations.append(
                    {
                        "component": "derived_b_total",
                        "p95": total_p95,
                        "baseline": baseline["derived_b_total"],
                        "limit": limit,
                    }
                )
        components = summary.get("components") or {}
        for key, stats in components.items():
            if key not in baseline:
                continue
            p95 = stats.get("p95") if isinstance(stats, dict) else None
            if not isinstance(p95, (int, float)):
                continue
            limit = baseline[key] * args.multiplier
            if p95 > limit:
                violations.append(
                    {
                        "component": key,
                        "p95": p95,
                        "baseline": baseline[key],
                        "limit": limit,
                    }
                )
        if violations:
            print(json.dumps({"violations": violations}, indent=2, sort_keys=True))
            return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
