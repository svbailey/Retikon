#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any, Dict, Iterable, List, Optional

from google.cloud import firestore


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


def infer_modality(object_name: str | None) -> Optional[str]:
    if not object_name:
        return None
    parts = object_name.strip("/").split("/")
    if len(parts) < 2:
        return None
    return parts[1]


def fetch_docs(
    client: firestore.Client,
    *,
    collection: str,
    prefix: str,
) -> List[firestore.DocumentSnapshot]:
    upper = f"{prefix}\uf8ff"
    query = (
        client.collection(collection)
        .where("object_name", ">=", prefix)
        .where("object_name", "<=", upper)
    )
    return list(query.stream())


def _pipe_ms(payload: dict) -> Optional[float]:
    metrics = payload.get("metrics") or {}
    pipe = coerce_float(metrics.get("pipe_ms"))
    if pipe is not None:
        return pipe
    pipeline = metrics.get("pipeline") or {}
    return coerce_float(pipeline.get("pipe_ms"))


def _cache_hit(payload: dict) -> Optional[bool]:
    value = payload.get("cache_hit")
    if isinstance(value, bool):
        return value
    return None


def collect_metrics(
    docs: Iterable[firestore.DocumentSnapshot],
    *,
    require_cache_hit: Optional[bool],
) -> Dict[str, Any]:
    pipe_ms: List[float] = []
    per_modality: Dict[str, List[float]] = {}
    total = 0
    matched = 0
    cache_hits = 0

    for doc in docs:
        total += 1
        payload = doc.to_dict() or {}
        cache_hit = _cache_hit(payload)
        if require_cache_hit is True and cache_hit is not True:
            continue
        if require_cache_hit is False and cache_hit is True:
            continue
        matched += 1
        if cache_hit is True:
            cache_hits += 1
        pipe = _pipe_ms(payload)
        if pipe is None:
            continue
        pipe_ms.append(pipe)
        modality = infer_modality(payload.get("object_name"))
        if modality:
            per_modality.setdefault(modality, []).append(pipe)

    summary = {
        "total_docs": total,
        "matched_docs": matched,
        "cache_hit_rate": (cache_hits / matched) if matched else None,
        "pipe_ms": summarize(pipe_ms),
        "pipe_ms_by_modality": {
            key: summarize(values) for key, values in per_modality.items()
        },
    }
    return summary


def _delta_pct(baseline: Optional[float], candidate: Optional[float]) -> Optional[float]:
    if baseline is None or candidate is None or baseline == 0:
        return None
    return round((1.0 - (candidate / baseline)) * 100.0, 2)


def _collect_run_docs(
    client: firestore.Client,
    *,
    collection: str,
    raw_prefix: str,
    run_id: str,
    modalities: List[str],
) -> List[firestore.DocumentSnapshot]:
    raw_prefix = raw_prefix.strip("/")
    docs: list[firestore.DocumentSnapshot] = []
    seen: set[str] = set()
    for modality in modalities:
        prefix = f"{raw_prefix}/{modality}/{run_id}/"
        for doc in fetch_docs(client, collection=collection, prefix=prefix):
            if doc.id in seen:
                continue
            seen.add(doc.id)
            docs.append(doc)
    return docs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare pipe_ms for baseline vs dedupe cache hits."
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--collection", default="ingestion_events")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--raw-prefix", required=True)
    parser.add_argument("--baseline-run-id", required=True)
    parser.add_argument("--dedupe-run-id", required=True)
    parser.add_argument(
        "--modalities",
        default="docs,images",
        help="Comma-separated modalities to include.",
    )
    args = parser.parse_args()

    modalities = [item.strip() for item in args.modalities.split(",") if item.strip()]
    client = firestore.Client(project=args.project)

    baseline_docs = _collect_run_docs(
        client,
        collection=args.collection,
        raw_prefix=args.raw_prefix,
        run_id=args.baseline_run_id,
        modalities=modalities,
    )
    dedupe_docs = _collect_run_docs(
        client,
        collection=args.collection,
        raw_prefix=args.raw_prefix,
        run_id=args.dedupe_run_id,
        modalities=modalities,
    )

    baseline_summary = collect_metrics(baseline_docs, require_cache_hit=False)
    dedupe_summary = collect_metrics(dedupe_docs, require_cache_hit=True)

    baseline_p95 = baseline_summary.get("pipe_ms", {}).get("p95")
    dedupe_p95 = dedupe_summary.get("pipe_ms", {}).get("p95")
    delta_overall = _delta_pct(baseline_p95, dedupe_p95)

    delta_by_modality: dict[str, Optional[float]] = {}
    baseline_mod = baseline_summary.get("pipe_ms_by_modality") or {}
    dedupe_mod = dedupe_summary.get("pipe_ms_by_modality") or {}
    for key, stats in baseline_mod.items():
        if not isinstance(stats, dict):
            continue
        baseline_mod_p95 = stats.get("p95")
        dedupe_mod_p95 = None
        if isinstance(dedupe_mod, dict) and isinstance(dedupe_mod.get(key), dict):
            dedupe_mod_p95 = dedupe_mod[key].get("p95")
        delta_by_modality[key] = _delta_pct(baseline_mod_p95, dedupe_mod_p95)

    payload = {
        "bucket": args.bucket,
        "raw_prefix": args.raw_prefix,
        "baseline_run_id": args.baseline_run_id,
        "dedupe_run_id": args.dedupe_run_id,
        "modalities": modalities,
        "baseline": baseline_summary,
        "dedupe": dedupe_summary,
        "pipe_ms_drop_pct": delta_overall,
        "pipe_ms_drop_pct_by_modality": delta_by_modality,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
