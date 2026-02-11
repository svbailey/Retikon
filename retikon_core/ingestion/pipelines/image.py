from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone

import fsspec
from PIL import Image, ImageOps

from retikon_core.config import Config
from retikon_core.embeddings import get_image_embedder
from retikon_core.embeddings.timeout import run_inference
from retikon_core.ingestion.pipelines.metrics import (
    CallTracker,
    StageTimer,
    build_stage_timings,
    timed_call,
)
from retikon_core.ingestion.pipelines.types import PipelineResult
from retikon_core.ingestion.types import IngestSource
from retikon_core.storage.manifest import (
    build_manifest,
    manifest_metrics_subset,
    write_manifest,
)
from retikon_core.storage.paths import (
    edge_part_uri,
    join_uri,
    manifest_uri,
    vertex_part_uri,
)
from retikon_core.storage.schemas import schema_for
from retikon_core.storage.writer import WriteResult, write_parquet
from retikon_core.tenancy import tenancy_fields


def _pipeline_model() -> str:
    return os.getenv("IMAGE_MODEL_NAME", "openai/clip-vit-base-patch32")


def _thumbnail_uri(output_root: str, media_asset_id: str) -> str:
    return join_uri(output_root, "thumbnails", media_asset_id, "image.jpg")


def _write_thumbnail(image: Image.Image, uri: str, width: int) -> int:
    if width <= 0:
        return 0
    thumb = image.copy()
    if thumb.width > width:
        height = max(1, int(thumb.height * (width / float(thumb.width))))
        thumb = thumb.resize((width, height))
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        thumb.save(tmp_path, format="JPEG", quality=85)
        bytes_written = os.path.getsize(tmp_path)
        fs, path = fsspec.core.url_to_fs(uri)
        fs.makedirs(os.path.dirname(path), exist_ok=True)
        with fs.open(path, "wb") as handle, open(tmp_path, "rb") as src:
            shutil.copyfileobj(src, handle)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return bytes_written


def ingest_image(
    *,
    source: IngestSource,
    config: Config,
    output_uri: str | None,
    pipeline_version: str,
    schema_version: str,
) -> PipelineResult:
    started_at = datetime.now(timezone.utc)
    output_root = output_uri or config.graph_root_uri()
    timer = StageTimer()
    calls = CallTracker()

    with timer.track("load_image"):
        with Image.open(source.local_path) as img:
            exif_img = ImageOps.exif_transpose(img)
            if exif_img is None:
                exif_img = img
            rgb = exif_img.convert("RGB")
            width, height = rgb.size
    with timer.track("image_embed"):
        embedder = get_image_embedder(512)
        vector = timed_call(
            calls,
            "image_embed",
            lambda: run_inference("image", lambda: embedder.encode([rgb])[0]),
        )

    media_asset_id = str(uuid.uuid4())
    image_asset_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    thumb_uri = None
    thumb_bytes = 0
    if config.video_thumbnail_width > 0:
        thumb_uri = _thumbnail_uri(output_root, media_asset_id)
        with timer.track("write_thumbnail"):
            thumb_bytes = _write_thumbnail(rgb, thumb_uri, config.video_thumbnail_width)

    media_row = {
        "id": media_asset_id,
        "uri": source.uri,
        "media_type": "image",
        "content_type": source.content_type or "application/octet-stream",
        "size_bytes": source.size_bytes or 0,
        "source_bucket": source.bucket,
        "source_object": source.name,
        "source_generation": source.generation,
        "checksum": source.md5_hash or source.crc32c,
        "duration_ms": None,
        "width_px": width,
        "height_px": height,
        "frame_count": None,
        "sample_rate_hz": None,
        "channels": None,
        **tenancy_fields(
            org_id=source.org_id,
            site_id=source.site_id,
            stream_id=source.stream_id,
        ),
        "created_at": now,
        "pipeline_version": pipeline_version,
        "schema_version": schema_version,
    }

    image_core_row = {
        "id": image_asset_id,
        "media_asset_id": media_asset_id,
        "frame_index": None,
        "timestamp_ms": None,
        "width_px": width,
        "height_px": height,
        "thumbnail_uri": thumb_uri,
        "embedding_model": _pipeline_model(),
        **tenancy_fields(
            org_id=source.org_id,
            site_id=source.site_id,
            stream_id=source.stream_id,
        ),
        "pipeline_version": pipeline_version,
        "schema_version": schema_version,
    }

    files: list[WriteResult] = []
    with timer.track("write_parquet"):
        files.append(
            write_parquet(
                [media_row],
                schema_for("MediaAsset", "core"),
                vertex_part_uri(output_root, "MediaAsset", "core", str(uuid.uuid4())),
            )
        )
        files.append(
            write_parquet(
                [image_core_row],
                schema_for("ImageAsset", "core"),
                vertex_part_uri(output_root, "ImageAsset", "core", str(uuid.uuid4())),
            )
        )
        files.append(
            write_parquet(
                [{"clip_vector": vector}],
                schema_for("ImageAsset", "vector"),
                vertex_part_uri(output_root, "ImageAsset", "vector", str(uuid.uuid4())),
            )
        )
        files.append(
            write_parquet(
                [
                    {
                        "src_id": image_asset_id,
                        "dst_id": media_asset_id,
                        "schema_version": schema_version,
                    }
                ],
                schema_for("DerivedFrom", "adj_list"),
                edge_part_uri(output_root, "DerivedFrom", str(uuid.uuid4())),
            )
        )

    parquet_bytes = sum(item.bytes_written for item in files)
    bytes_raw = source.size_bytes or 0
    vector_dims = len(vector) if vector is not None else 0
    raw_timings_preview = timer.summary()
    stage_timings_preview = build_stage_timings(
        raw_timings_preview,
        {
            "load_image": "decode_ms",
            "image_embed": "embed_image_ms",
            "write_thumbnail": "write_blobs_ms",
            "write_parquet": "write_parquet_ms",
            "write_manifest": "write_manifest_ms",
        },
    )
    manifest_metrics = manifest_metrics_subset(
        {
            "io": {
                "bytes_raw": bytes_raw,
                "bytes_parquet": parquet_bytes,
                "bytes_thumbnails": thumb_bytes,
                "bytes_derived": parquet_bytes + thumb_bytes,
            },
            "quality": {
                "width_px": width,
                "height_px": height,
            },
            "embeddings": {
                "image": {
                    "count": 1,
                    "dims": vector_dims,
                }
            },
            "evidence": {
                "frames": 1,
                "snippets": 0,
                "segments": 0,
            },
            "stage_timings_ms": stage_timings_preview,
        }
    )
    completed_at = datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())
    with timer.track("write_manifest"):
        manifest = build_manifest(
            pipeline_version=pipeline_version,
            schema_version=schema_version,
            counts={
                "MediaAsset": 1,
                "ImageAsset": 1,
                "DerivedFrom": 1,
            },
            files=files,
            started_at=started_at,
            completed_at=completed_at,
            metrics=manifest_metrics,
        )
        manifest_path = manifest_uri(output_root, run_id)
        write_manifest(manifest, manifest_path)
    raw_timings = timer.summary()
    stage_timings_ms = build_stage_timings(
        raw_timings,
        {
            "load_image": "decode_ms",
            "image_embed": "embed_image_ms",
            "write_thumbnail": "write_blobs_ms",
            "write_parquet": "write_parquet_ms",
            "write_manifest": "write_manifest_ms",
        },
    )
    metrics = {
        "timings_ms": raw_timings,
        "stage_timings_ms": stage_timings_ms,
        "pipe_ms": round(sum(stage_timings_ms.values()), 2),
        "model_calls": calls.summary(),
        "io": {
            "bytes_raw": bytes_raw,
            "bytes_parquet": parquet_bytes,
            "bytes_thumbnails": thumb_bytes,
            "bytes_derived": parquet_bytes + thumb_bytes,
        },
        "quality": {
            "width_px": width,
            "height_px": height,
        },
        "embeddings": {
            "image": {
                "count": 1,
                "dims": vector_dims,
            }
        },
        "evidence": {
            "frames": 1,
            "snippets": 0,
            "segments": 0,
        },
    }

    return PipelineResult(
        counts={
            "MediaAsset": 1,
            "ImageAsset": 1,
            "DerivedFrom": 1,
        },
        manifest_uri=manifest_path,
        media_asset_id=media_asset_id,
        metrics=metrics,
    )
