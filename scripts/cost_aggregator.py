#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import fsspec
from google.cloud import firestore


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
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


def _summarize(values: list[float]) -> dict[str, float]:
    return {
        "count": float(len(values)),
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
    }


def _coerce_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _vector_count(embeddings: dict[str, Any]) -> int:
    total = 0
    for key in ("text", "image", "audio"):
        entry = embeddings.get(key) or {}
        count = entry.get("count")
        if isinstance(count, (int, float)):
            total += int(count)
    return total


def _model_seconds(model_calls: dict[str, Any]) -> float:
    total_ms = 0.0
    if not isinstance(model_calls, dict):
        return 0.0
    for entry in model_calls.values():
        if not isinstance(entry, dict):
            continue
        duration = entry.get("total_ms") or entry.get("duration_ms")
        if isinstance(duration, (int, float)):
            total_ms += float(duration)
    return round(total_ms / 1000.0, 4)


def _asset_uri(payload: dict) -> str:
    bucket = payload.get("object_bucket")
    name = payload.get("object_name")
    if bucket and name:
        return f"gs://{bucket}/{name}"
    return name or "unknown"


def _fetch_docs(
    client: firestore.Client,
    *,
    collection: str,
    prefix: str,
) -> list[firestore.DocumentSnapshot]:
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


def _open_output(path: str):
    fs, fs_path = fsspec.core.url_to_fs(path)
    directory = os.path.dirname(fs_path)
    if directory:
        fs.makedirs(directory, exist_ok=True)
    return fs.open(fs_path, "w")


def _build_record(
    doc: firestore.DocumentSnapshot,
    *,
    index_seconds_per_vector: float,
) -> dict[str, Any]:
    payload = doc.to_dict() or {}
    metrics = payload.get("metrics") or {}
    pipeline = metrics.get("pipeline") or {}
    io_payload = pipeline.get("io") or {}
    system = metrics.get("system") or {}
    embeddings = pipeline.get("embeddings") or {}
    model_calls = pipeline.get("model_calls") or {}

    cpu_user = _coerce_float(system.get("cpu_user_s")) or 0.0
    cpu_sys = _coerce_float(system.get("cpu_sys_s")) or 0.0
    cpu_seconds = round(cpu_user + cpu_sys, 4)

    raw_bytes = _coerce_float(io_payload.get("bytes_raw")) or 0.0
    derived_bytes = _coerce_float(io_payload.get("derived_b_total"))
    if derived_bytes is None:
        derived_bytes = _coerce_float(io_payload.get("bytes_derived")) or 0.0

    vectors = _vector_count(embeddings)
    index_seconds = round(vectors * index_seconds_per_vector, 4)

    return {
        "ingest_id": payload.get("ingest_id") or doc.id,
        "org_id": payload.get("org_id"),
        "asset_uri": _asset_uri(payload),
        "asset_type": payload.get("asset_type"),
        "cost_cpu_seconds": cpu_seconds,
        "cost_model_seconds": _model_seconds(model_calls),
        "cost_raw_bytes": raw_bytes,
        "cost_derived_bytes": derived_bytes,
        "cost_index_seconds_est": index_seconds,
        "vector_count": vectors,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate per-asset cost summaries.")
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
    parser.add_argument("--output", required=True, help="Output JSONL path (local or gs://)")
    parser.add_argument(
        "--index-seconds-per-vector",
        type=float,
        default=0.0,
        help="Estimate of index build seconds per vector.",
    )
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
        for doc in _fetch_docs(client, collection=args.collection, prefix=prefix):
            if doc.id in seen:
                continue
            seen.add(doc.id)
            docs.append(doc)
    if not docs:
        print("No ingestion docs found for prefix.")
        return 1

    records = [
        _build_record(doc, index_seconds_per_vector=args.index_seconds_per_vector)
        for doc in docs
    ]

    with _open_output(args.output) as handle:
        for record in records:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

    cpu_s = [record["cost_cpu_seconds"] for record in records]
    model_s = [record["cost_model_seconds"] for record in records]
    derived_b = [record["cost_derived_bytes"] for record in records]
    summary = {
        "run_id": args.run_id,
        "run_ids_by_modality": run_ids_by_modality,
        "count": len(records),
        "cpu_seconds": _summarize(cpu_s),
        "model_seconds": _summarize(model_s),
        "derived_bytes": _summarize(derived_b),
        "output": args.output,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
