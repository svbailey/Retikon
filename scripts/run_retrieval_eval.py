from __future__ import annotations

import argparse
import base64
import json
import math
import os
import time
from pathlib import Path
from typing import Any

import httpx

from retikon_core.query_engine.query_runner import rank_of_expected, top_k_overlap


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lower = math.floor(k)
    upper = math.ceil(k)
    if lower == upper:
        return ordered[int(k)]
    weight = k - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _load_image_base64(path: str) -> str:
    with open(path, "rb") as handle:
        return base64.b64encode(handle.read()).decode("ascii")


def _load_queries(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="ascii"))
        if not isinstance(payload, dict):
            raise ValueError("Eval JSON must be an object")
        items = payload.get("queries")
        if not isinstance(items, list):
            raise ValueError("Eval JSON must include a queries list")
        return [item for item in items if isinstance(item, dict)]
    queries: list[dict[str, Any]] = []
    with path.open("r", encoding="ascii") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            queries.append(json.loads(raw))
    return queries


def _build_payload(entry: dict[str, Any], top_k: int) -> dict[str, Any]:
    payload: dict[str, Any] = {"top_k": top_k}
    if entry.get("query_text"):
        payload["query_text"] = entry["query_text"]
    if entry.get("image_path"):
        payload["image_base64"] = _load_image_base64(entry["image_path"])
    if entry.get("mode"):
        payload["mode"] = entry["mode"]
    if entry.get("modalities"):
        payload["modalities"] = entry["modalities"]
    if entry.get("search_type"):
        payload["search_type"] = entry["search_type"]
    if entry.get("metadata_filters"):
        payload["metadata_filters"] = entry["metadata_filters"]
    return payload


def _summarize_metric(values: list[float]) -> dict[str, float]:
    return {
        "mean": round(sum(values) / len(values), 4) if values else 0.0,
        "p50": round(_percentile(values, 0.5), 4),
        "p95": round(_percentile(values, 0.95), 4),
    }


def _aggregate(entries: list[dict[str, Any]]) -> dict[str, Any]:
    recall_10 = [entry["recall_10"] for entry in entries]
    recall_50 = [entry["recall_50"] for entry in entries]
    mrr_10 = [entry["mrr_10"] for entry in entries]
    overlap = [entry["top_k_overlap"] for entry in entries]
    latencies = [entry["latency_ms"] for entry in entries]
    return {
        "count": len(entries),
        "recall_10": round(sum(recall_10) / len(recall_10), 4) if recall_10 else 0.0,
        "recall_50": round(sum(recall_50) / len(recall_50), 4) if recall_50 else 0.0,
        "mrr_10": round(sum(mrr_10) / len(mrr_10), 4) if mrr_10 else 0.0,
        "top_k_overlap": round(sum(overlap) / len(overlap), 4) if overlap else 0.0,
        "latency_ms": _summarize_metric(latencies),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run retrieval eval against query service.")
    parser.add_argument(
        "--eval-file",
        required=True,
        help="Path to queries.jsonl or golden_queries.json",
    )
    parser.add_argument("--query-url", help="Query endpoint URL")
    parser.add_argument("--auth-token", help="Bearer token for query endpoint")
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--output", help="Optional JSON output path")
    parser.add_argument("--eval-run-id", help="Optional eval run id")
    args = parser.parse_args()

    query_url = args.query_url or os.getenv("QUERY_URL")
    if not query_url:
        raise SystemExit("--query-url or QUERY_URL is required")

    auth_token = args.auth_token or os.getenv("RETIKON_AUTH_TOKEN")
    if not auth_token:
        raise SystemExit("--auth-token or RETIKON_AUTH_TOKEN is required")

    eval_path = Path(args.eval_file)
    queries = _load_queries(eval_path)
    if not queries:
        raise SystemExit("No queries found.")

    top_k = max(1, min(args.top_k, 50))
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}",
    }

    per_query: list[dict[str, Any]] = []
    per_modality: dict[str, list[dict[str, Any]]] = {}

    with httpx.Client(timeout=args.timeout) as client:
        for entry in queries:
            payload = _build_payload(entry, top_k)
            start = time.perf_counter()
            response = client.post(query_url, headers=headers, json=payload)
            latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
            if response.status_code < 200 or response.status_code >= 300:
                raise SystemExit(
                    f"Query failed ({response.status_code}): {response.text}"
                )
            data = response.json()
            results = [item.get("uri") for item in data.get("results", []) if item.get("uri")]
            expected = entry.get("expected_uris") or []
            rank = rank_of_expected(results[:top_k], expected)
            recall_10 = 1.0 if rank and rank <= 10 else 0.0
            recall_50 = 1.0 if rank and rank <= 50 else 0.0
            mrr_10 = round(1.0 / rank, 6) if rank and rank <= 10 else 0.0
            overlap = round(top_k_overlap(results, expected, top_k), 6)

            record = {
                "id": entry.get("id"),
                "modality": entry.get("modality", "unknown"),
                "rank": rank,
                "recall_10": recall_10,
                "recall_50": recall_50,
                "mrr_10": mrr_10,
                "top_k_overlap": overlap,
                "latency_ms": latency_ms,
            }
            per_query.append(record)
            per_modality.setdefault(record["modality"], []).append(record)

    summary = {
        "eval_run_id": args.eval_run_id or f"eval-{int(time.time())}",
        "query_url": query_url,
        "top_k": top_k,
        "overall": _aggregate(per_query),
        "per_modality": {key: _aggregate(items) for key, items in per_modality.items()},
        "queries": per_query,
    }

    print(json.dumps(summary, indent=2, sort_keys=True))

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="ascii")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
