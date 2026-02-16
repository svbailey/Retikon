#!/usr/bin/env python3
import argparse
import json
import sys
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


def collect_metrics(
    docs: Iterable[firestore.DocumentSnapshot],
    *,
    bucket: str,
    quality_rules: Dict[str, Any],
) -> Dict[str, Any]:
    wall_ms: List[float] = []
    queue_wait_ms: List[float] = []
    pipe_ms: List[float] = []
    cpu_s: List[float] = []
    memory_peak_kb: List[float] = []
    bytes_derived: List[float] = []
    stage_timings: Dict[str, List[float]] = {}
    cold_start_flags: List[bool] = []
    cold_wall_ms: List[float] = []
    warm_wall_ms: List[float] = []
    instance_ids: List[str] = []
    quality_failures: List[Dict[str, str]] = []

    for doc in docs:
        payload = doc.to_dict() or {}
        metrics = payload.get("metrics") or {}
        pipeline = metrics.get("pipeline") or {}
        wall = coerce_float(metrics.get("wall_ms"))
        if wall is not None:
            wall_ms.append(wall)
        queue_wait = coerce_float(metrics.get("queue_wait_ms"))
        if queue_wait is not None:
            queue_wait_ms.append(queue_wait)
        pipe = coerce_float(metrics.get("pipe_ms"))
        if pipe is None:
            pipe = coerce_float(pipeline.get("pipe_ms"))
        if pipe is not None:
            pipe_ms.append(pipe)
        system = metrics.get("system") or {}
        cpu_user = coerce_float(system.get("cpu_user_s"))
        cpu_sys = coerce_float(system.get("cpu_sys_s"))
        if cpu_user is not None and cpu_sys is not None:
            cpu_s.append(cpu_user + cpu_sys)
        mem_kb = coerce_float(system.get("memory_peak_kb"))
        if mem_kb is not None:
            memory_peak_kb.append(mem_kb)
        instance_id = system.get("instance_id")
        if isinstance(instance_id, str) and instance_id:
            instance_ids.append(instance_id)
        cold_start = system.get("cold_start")
        if isinstance(cold_start, bool):
            cold_start_flags.append(cold_start)
            if wall is not None:
                if cold_start:
                    cold_wall_ms.append(wall)
                else:
                    warm_wall_ms.append(wall)
        io = pipeline.get("io") or {}
        derived = coerce_float(io.get("bytes_derived"))
        if derived is not None:
            bytes_derived.append(derived)
        stage = metrics.get("stage_timings_ms") or pipeline.get("stage_timings_ms") or {}
        if isinstance(stage, dict):
            for key, value in stage.items():
                val = coerce_float(value)
                if val is None:
                    continue
                stage_timings.setdefault(key, []).append(val)

        quality = pipeline.get("quality") or {}
        embeddings = pipeline.get("embeddings") or {}
        object_name = payload.get("object_name", "unknown")
        object_bucket = payload.get("object_bucket")
        if object_bucket and object_bucket != bucket:
            continue
        asset_ref = f"gs://{object_bucket}/{object_name}" if object_bucket else object_name
        modality = infer_modality(object_name)
        if modality == "docs":
            min_words, min_chunks = expected_doc_thresholds(
                object_name,
                default_words=quality_rules["doc_min_word_count"],
                default_chunks=quality_rules["doc_min_chunk_count"],
            )
            word_count = quality.get("word_count")
            chunk_count = quality.get("chunk_count")
            text_embeddings = (embeddings.get("text") or {}).get("count")
            if isinstance(word_count, (int, float)) and word_count < min_words:
                quality_failures.append(
                    {"asset_uri": asset_ref, "reason": "word_count_below_min"}
                )
            if isinstance(chunk_count, (int, float)) and chunk_count < min_chunks:
                quality_failures.append(
                    {"asset_uri": asset_ref, "reason": "chunk_count_below_min"}
                )
            if (
                isinstance(chunk_count, (int, float))
                and isinstance(text_embeddings, (int, float))
                and text_embeddings < chunk_count
            ):
                quality_failures.append(
                    {"asset_uri": asset_ref, "reason": "embeddings_lt_chunks"}
                )
        elif modality == "images":
            min_dim = expected_image_min_dim(
                object_name,
                quality_rules["image_min_dim"],
            )
            min_embed = quality_rules["image_min_embed_count"]
            width = quality.get("width_px")
            height = quality.get("height_px")
            image_embeddings = (embeddings.get("image") or {}).get("count")
            if isinstance(width, (int, float)) and width < min_dim:
                quality_failures.append(
                    {"asset_uri": asset_ref, "reason": "width_below_min"}
                )
            if isinstance(height, (int, float)) and height < min_dim:
                quality_failures.append(
                    {"asset_uri": asset_ref, "reason": "height_below_min"}
                )
            if isinstance(image_embeddings, (int, float)) and image_embeddings < min_embed:
                quality_failures.append(
                    {"asset_uri": asset_ref, "reason": "embed_count_below_min"}
                )

    stage_p95 = {key: percentile(values, 95) for key, values in stage_timings.items()}
    cold_start_rate = None
    if cold_start_flags:
        cold_start_rate = sum(1 for item in cold_start_flags if item) / len(
            cold_start_flags
        )
    instance_unique_count = None
    instance_sample_count = None
    instance_unique_rate = None
    if instance_ids:
        instance_sample_count = len(instance_ids)
        instance_unique_count = len(set(instance_ids))
        instance_unique_rate = instance_unique_count / instance_sample_count
    return {
        "wall_ms": summarize(wall_ms),
        "queue_wait_ms": summarize(queue_wait_ms),
        "pipe_ms": summarize(pipe_ms),
        "cpu_s": summarize(cpu_s),
        "memory_peak_kb": summarize(memory_peak_kb),
        "bytes_derived": summarize(bytes_derived),
        "stage_timings_p95": stage_p95,
        "cold_start_rate": cold_start_rate,
        "cold_start_wall_ms": summarize(cold_wall_ms),
        "warm_wall_ms": summarize(warm_wall_ms),
        "instance_sample_count": instance_sample_count,
        "instance_unique_count": instance_unique_count,
        "instance_unique_rate": instance_unique_rate,
        "quality_failures": quality_failures,
    }


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


def infer_modality(object_name: str | None) -> Optional[str]:
    if not object_name:
        return None
    parts = object_name.strip("/").split("/")
    if len(parts) < 2:
        return None
    return parts[1]


def _basename(object_name: str | None) -> str:
    if not object_name:
        return ""
    return object_name.rsplit("/", 1)[-1].lower()


def expected_doc_thresholds(
    object_name: str | None,
    *,
    default_words: int,
    default_chunks: int,
) -> tuple[int, int]:
    name = _basename(object_name)
    if "doc-minimal" in name:
        return 5, 1
    if "doc-typical" in name:
        return 50, 3
    if "doc-multipage" in name or "doc-long" in name:
        return 200, 8
    return default_words, default_chunks


def expected_image_min_dim(object_name: str | None, default_dim: int) -> int:
    name = _basename(object_name)
    if "img-256" in name:
        return 256
    if "img-1024" in name:
        return 1024
    if "img-large" in name or "img-2048" in name:
        return 1024
    return default_dim


def write_markdown(path: str, summary: Dict[str, Any]) -> None:
    lines = []
    lines.append("# Ingest baseline summary\n")
    for modality, stats in summary.items():
        lines.append(f"## {modality}\n")
        lines.append("| Metric | p50 | p95 | p99 | count |\n")
        lines.append("| --- | --- | --- | --- | --- |\n")
        for metric in ("wall_ms", "queue_wait_ms", "pipe_ms", "cpu_s", "memory_peak_kb", "bytes_derived"):
            values = stats.get(metric, {})
            lines.append(
                f"| {metric} | {values.get('p50')} | {values.get('p95')} | {values.get('p99')} | {values.get('count')} |\n"
            )
        lines.append("\n")
        cold_rate = stats.get("cold_start_rate")
        if cold_rate is not None:
            lines.append(f"Cold start rate: {round(cold_rate * 100.0, 2)}%\n\n")
            lines.append("| Metric | p50 | p95 | p99 | count |\n")
            lines.append("| --- | --- | --- | --- | --- |\n")
            for metric in ("cold_start_wall_ms", "warm_wall_ms"):
                values = stats.get(metric, {})
                lines.append(
                    f"| {metric} | {values.get('p50')} | {values.get('p95')} | {values.get('p99')} | {values.get('count')} |\n"
                )
            lines.append("\n")
        instance_unique = stats.get("instance_unique_count")
        instance_samples = stats.get("instance_sample_count")
        instance_rate = stats.get("instance_unique_rate")
        if instance_unique is not None and instance_samples is not None:
            rate_pct = round(instance_rate * 100.0, 2) if isinstance(instance_rate, float) else None
            rate_text = f"{rate_pct}%" if rate_pct is not None else "n/a"
            lines.append(
                f"Instance churn: {instance_unique}/{instance_samples} unique ({rate_text})\n\n"
            )
        lines.append("Stage timings p95 (ms):\n\n")
        lines.append("```\n")
        for key, value in sorted((stats.get("stage_timings_p95") or {}).items()):
            lines.append(f"{key}: {value}\n")
        lines.append("```\n\n")
    with open(path, "w", encoding="utf-8") as handle:
        handle.writelines(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Report ingest baselines from Firestore.")
    parser.add_argument("--project", required=True, help="GCP project id")
    parser.add_argument("--bucket", required=True, help="Raw bucket name")
    parser.add_argument("--raw-prefix", default="raw_clean", help="Raw prefix (default: raw_clean)")
    parser.add_argument("--run-id", required=True, help="Run id used in asset URIs")
    parser.add_argument("--collection", default="ingestion_events", help="Firestore collection")
    parser.add_argument(
        "--modalities",
        default="docs,images,audio,videos",
        help="Comma-separated modalities to include",
    )
    parser.add_argument("--quality-check", action="store_true", help="Enable quality checks")
    parser.add_argument("--doc-min-word-count", type=int, default=5)
    parser.add_argument("--doc-min-chunk-count", type=int, default=1)
    parser.add_argument("--image-min-dim", type=int, default=64)
    parser.add_argument("--image-min-embed-count", type=int, default=1)
    parser.add_argument("--md-out", help="Write Markdown summary to path")
    args = parser.parse_args()

    client = firestore.Client(project=args.project)
    modalities = [m.strip() for m in args.modalities.split(",") if m.strip()]
    summary: Dict[str, Any] = {}
    quality_rules = {
        "doc_min_word_count": args.doc_min_word_count,
        "doc_min_chunk_count": args.doc_min_chunk_count,
        "image_min_dim": args.image_min_dim,
        "image_min_embed_count": args.image_min_embed_count,
    }
    has_failures = False

    for modality in modalities:
        object_prefix = f"{args.raw_prefix}/{modality}/{args.run_id}/"
        docs = fetch_docs(client, collection=args.collection, prefix=object_prefix)
        stats = collect_metrics(docs, bucket=args.bucket, quality_rules=quality_rules)
        summary[modality] = stats
        if args.quality_check and stats.get("quality_failures"):
            has_failures = True

    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.md_out:
        write_markdown(args.md_out, summary)
    if args.quality_check and has_failures:
        print("Quality checks failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
