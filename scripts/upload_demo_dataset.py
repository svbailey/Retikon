from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from google.cloud import storage

DOC_EXT = {".pdf", ".docx", ".pptx", ".csv", ".tsv", ".xlsx", ".xls", ".txt"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


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
    raise ValueError(f"Unsupported demo fixture extension: {ext}")


def _iter_files(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    return [path for path in sorted(source.rglob("*")) if path.is_file()]


def _upload_object(
    client: storage.Client,
    bucket_name: str,
    object_name: str,
    path: Path,
) -> str:
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_name)
    blob.upload_from_filename(str(path))
    return object_name


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload demo fixtures to the raw bucket."
    )
    parser.add_argument("--bucket", default=os.getenv("RAW_BUCKET"))
    parser.add_argument("--source", default="tests/fixtures")
    parser.add_argument("--prefix", default="raw")
    parser.add_argument("--run-id", default=time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    if not args.bucket:
        raise SystemExit("--bucket or RAW_BUCKET is required")

    source = Path(args.source)
    files = _iter_files(source)
    if not files:
        raise SystemExit(f"No files found under {source}")

    storage_client = storage.Client()
    uploaded: list[str] = []

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = []
        for path in files:
            category = _classify(path)
            object_name = f"{args.prefix}/{category}/{args.run_id}/{path.name}"
            futures.append(
                executor.submit(
                    _upload_object,
                    storage_client,
                    args.bucket,
                    object_name,
                    path,
                )
            )
        for future in as_completed(futures):
            uploaded.append(future.result())

    print("Uploaded objects:")
    for object_name in sorted(uploaded):
        print(f"- gs://{args.bucket}/{object_name}")


if __name__ == "__main__":
    main()
