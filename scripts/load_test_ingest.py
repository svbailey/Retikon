from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from google.cloud import firestore, storage

DOC_EXT = {".pdf", ".docx", ".pptx", ".csv", ".tsv", ".xlsx", ".xls", ".txt"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
SUPPORTED_EXT = DOC_EXT | IMAGE_EXT | AUDIO_EXT | VIDEO_EXT


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * pct
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _classify(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in DOC_EXT:
        return "docs"
    if ext in IMAGE_EXT:
        return "images"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in VIDEO_EXT:
        return "videos"
    raise ValueError(f"Unsupported fixture extension: {ext}")


def _normalize_mix_key(value: str) -> str:
    key = value.strip().lower()
    if key in {"doc", "docs", "document", "documents"}:
        return "docs"
    if key in {"image", "images"}:
        return "images"
    if key in {"audio", "audios"}:
        return "audio"
    if key in {"video", "videos"}:
        return "videos"
    raise ValueError(f"Unsupported mix modality: {value}")


def _parse_mix(raw: str | None) -> dict[str, float] | None:
    if not raw:
        return None
    mix: dict[str, float] = {}
    for item in raw.split(","):
        if not item.strip():
            continue
        if "=" not in item:
            raise ValueError(f"Invalid mix entry: {item}")
        key, value = item.split("=", 1)
        modality = _normalize_mix_key(key)
        weight = float(value)
        if weight <= 0:
            continue
        mix[modality] = mix.get(modality, 0.0) + weight
    if not mix:
        return None
    return mix


def _interleave(files_by_modality: dict[str, list[Path]]) -> list[Path]:
    ordered = sorted(files_by_modality.keys())
    indices = {modality: 0 for modality in ordered}
    total = sum(len(items) for items in files_by_modality.values())
    output: list[Path] = []
    while len(output) < total:
        for modality in ordered:
            items = files_by_modality[modality]
            idx = indices[modality]
            if idx >= len(items):
                continue
            output.append(items[idx])
            indices[modality] = idx + 1
            if len(output) >= total:
                break
    return output


def _apply_mix(files: list[Path], count: int, mix: dict[str, float]) -> list[Path]:
    by_modality: dict[str, list[Path]] = {"docs": [], "images": [], "audio": [], "videos": []}
    for path in files:
        by_modality[_classify(path)].append(path)
    missing = [modality for modality, weight in mix.items() if weight > 0 and not by_modality.get(modality)]
    if missing:
        raise ValueError(f"Missing fixtures for modalities: {', '.join(sorted(missing))}")

    total_weight = sum(mix.values())
    raw_counts = {
        modality: (count * (weight / total_weight)) for modality, weight in mix.items()
    }
    base_counts = {modality: int(raw) for modality, raw in raw_counts.items()}
    remainder = count - sum(base_counts.values())
    if remainder > 0:
        order = sorted(
            mix.keys(),
            key=lambda modality: raw_counts[modality] - base_counts[modality],
            reverse=True,
        )
        for modality in order[:remainder]:
            base_counts[modality] += 1

    expanded: dict[str, list[Path]] = {}
    for modality, target in base_counts.items():
        if target <= 0:
            continue
        expanded[modality] = _repeat_files(by_modality[modality], target)
    return _interleave(expanded)


def _iter_files(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    return [
        path
        for path in sorted(source.rglob("*"))
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXT
    ]


def _doc_id(bucket: str, object_name: str, generation: int) -> str:
    payload = f"{bucket}/{object_name}#{generation}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _upload_object(
    client: storage.Client,
    bucket_name: str,
    object_name: str,
    path: Path,
    unique_suffix: bytes | None = None,
) -> tuple[str, int, int]:
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_name)
    if unique_suffix:
        payload = path.read_bytes() + unique_suffix
        content_type, _ = mimetypes.guess_type(path.name)
        blob.upload_from_string(payload, content_type=content_type)
        generation = int(blob.generation or 0)
        return object_name, generation, len(payload)
    blob.upload_from_filename(str(path))
    generation = int(blob.generation or 0)
    return object_name, generation, path.stat().st_size


def _poll_firestore(
    project: str,
    doc_ids: dict[str, float],
    timeout: float,
    interval: float,
) -> dict[str, float]:
    client = firestore.Client(project=project)
    completed: dict[str, float] = {}
    deadline = time.time() + timeout
    pending = dict(doc_ids)

    while pending and time.time() < deadline:
        for doc_id, started_at in list(pending.items()):
            snapshot = client.collection("ingestion_events").document(doc_id).get()
            if not snapshot.exists:
                continue
            data = snapshot.to_dict() or {}
            status = data.get("status")
            if status in {"COMPLETED", "FAILED", "DLQ"}:
                completed[doc_id] = time.time() - started_at
                pending.pop(doc_id, None)
        if pending:
            time.sleep(interval)

    return completed


def _repeat_files(files: list[Path], count: int) -> list[Path]:
    if not files:
        raise ValueError("No files found for ingestion load test.")
    if count <= len(files):
        return files[:count]
    expanded: list[Path] = []
    while len(expanded) < count:
        expanded.extend(files)
    return expanded[:count]


def main() -> None:
    parser = argparse.ArgumentParser(description="Load test ingestion via GCS uploads.")
    parser.add_argument("--bucket", default=os.getenv("RAW_BUCKET"))
    parser.add_argument("--source", default="tests/fixtures")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--prefix", default="raw")
    parser.add_argument("--run-id", default=time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument(
        "--mix",
        help="Optional modality mix (e.g. docs=0.3,images=0.4,audio=0.2,videos=0.1)",
    )
    parser.add_argument("--poll", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument(
        "--unique",
        action="store_true",
        help="Append a per-upload suffix to avoid dedupe.",
    )
    args = parser.parse_args()

    if not args.bucket:
        raise SystemExit("--bucket or RAW_BUCKET is required")

    source = Path(args.source)
    all_files = _iter_files(source)
    mix = _parse_mix(args.mix)
    if mix:
        files = _apply_mix(all_files, args.count, mix)
    else:
        files = _repeat_files(all_files, args.count)
    storage_client = storage.Client()

    uploads: list[tuple[str, int, int]] = []
    doc_ids: dict[str, float] = {}

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = []
        for idx, path in enumerate(files):
            category = _classify(path)
            object_name = f"{args.prefix}/{category}/{args.run_id}/{idx}-{path.name}"
            unique_suffix = None
            if args.unique:
                unique_suffix = f"\n--unique-{uuid.uuid4().hex}--\n".encode("ascii")
            futures.append(
                executor.submit(
                    _upload_object,
                    storage_client,
                    args.bucket,
                    object_name,
                    path,
                    unique_suffix,
                )
            )
        for future in as_completed(futures):
            object_name, generation, size_bytes = future.result()
            uploads.append((object_name, generation, size_bytes))
            doc_ids[_doc_id(args.bucket, object_name, generation)] = time.time()
    elapsed = time.perf_counter() - start

    summary = {
        "bucket": args.bucket,
        "uploads": len(uploads),
        "bytes_total": sum(item[2] for item in uploads),
        "elapsed_seconds": round(elapsed, 4),
        "throughput_rps": round(len(uploads) / elapsed, 4) if elapsed > 0 else 0.0,
        "polling": args.poll,
    }
    if mix:
        mix_counts: dict[str, int] = {}
        for path in files:
            modality = _classify(path)
            mix_counts[modality] = mix_counts.get(modality, 0) + 1
        summary["mix"] = mix_counts

    if args.poll:
        if not args.project:
            raise SystemExit(
                "--project or GOOGLE_CLOUD_PROJECT is required for polling"
            )
        completed = _poll_firestore(
            project=args.project,
            doc_ids=doc_ids,
            timeout=args.timeout,
            interval=args.poll_interval,
        )
        if completed:
            durations = list(completed.values())
            summary.update(
                {
                    "completed": len(completed),
                    "completion_p50_s": round(_percentile(durations, 0.5), 2),
                    "completion_p95_s": round(_percentile(durations, 0.95), 2),
                }
            )
        else:
            summary.update({"completed": 0})

    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
