from __future__ import annotations

import math
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import fsspec
from PIL import Image

from retikon_core.config import Config
from retikon_core.embeddings import (
    get_audio_embedder,
    get_image_embedder,
    get_text_embedder,
)
from retikon_core.errors import PermanentError
from retikon_core.ingestion.download import cleanup_tmp
from retikon_core.ingestion.media import extract_audio, extract_keyframes, probe_media
from retikon_core.ingestion.pipelines.types import PipelineResult
from retikon_core.ingestion.transcribe import transcribe_audio
from retikon_core.ingestion.types import IngestSource
from retikon_core.storage.manifest import build_manifest, write_manifest
from retikon_core.storage.paths import (
    edge_part_uri,
    join_uri,
    manifest_uri,
    vertex_part_uri,
)
from retikon_core.storage.schemas import schema_for
from retikon_core.storage.writer import WriteResult, write_parquet
from retikon_core.tenancy import tenancy_fields


def _text_model() -> str:
    return os.getenv("TEXT_MODEL_NAME", "BAAI/bge-base-en-v1.5")


def _image_model() -> str:
    return os.getenv("IMAGE_MODEL_NAME", "openai/clip-vit-base-patch32")


def _audio_model() -> str:
    return os.getenv("AUDIO_MODEL_NAME", "laion/clap-htsat-fused")


def _resolve_fps(config: Config) -> float:
    if config.video_sample_interval_seconds > 0:
        return 1.0 / config.video_sample_interval_seconds
    return float(config.video_sample_fps)


def _thumbnail_uri(output_root: str, media_asset_id: str, frame_index: int) -> str:
    return join_uri(
        output_root,
        "thumbnails",
        media_asset_id,
        f"frame-{frame_index:05d}.jpg",
    )


def _write_thumbnail(
    image: Image.Image,
    uri: str,
    width: int,
) -> None:
    if width <= 0:
        return
    thumb = image.copy()
    if thumb.width > width:
        height = max(1, int(thumb.height * (width / float(thumb.width))))
        thumb = thumb.resize((width, height))
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        thumb.save(tmp_path, format="JPEG", quality=85)
        fs, path = fsspec.core.url_to_fs(uri)
        fs.makedirs(os.path.dirname(path), exist_ok=True)
        with fs.open(path, "wb") as handle, open(tmp_path, "rb") as src:
            shutil.copyfileobj(src, handle)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def ingest_video(
    *,
    source: IngestSource,
    config: Config,
    output_uri: str | None,
    pipeline_version: str,
    schema_version: str,
) -> PipelineResult:
    started_at = datetime.now(timezone.utc)
    probe = probe_media(source.local_path)
    if probe.duration_seconds > config.max_video_seconds:
        raise PermanentError("Video duration exceeds max")

    output_root = output_uri or config.graph_root_uri()
    media_asset_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    duration_ms = int(probe.duration_seconds * 1000.0)
    fps = _resolve_fps(config)
    if config.max_frames_per_video > 0:
        expected_frames = int(math.ceil(probe.duration_seconds * fps))
        if probe.frame_count is not None:
            expected_frames = max(expected_frames, probe.frame_count)
        if expected_frames > config.max_frames_per_video:
            raise PermanentError("Video exceeds max frames")

    media_row = {
        "id": media_asset_id,
        "uri": source.uri,
        "media_type": "video",
        "content_type": source.content_type or "application/octet-stream",
        "size_bytes": source.size_bytes or 0,
        "source_bucket": source.bucket,
        "source_object": source.name,
        "source_generation": source.generation,
        "checksum": source.md5_hash or source.crc32c,
        "duration_ms": duration_ms,
        "width_px": probe.video_width,
        "height_px": probe.video_height,
        "frame_count": probe.frame_count,
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

    frames_dir = tempfile.mkdtemp(prefix="retikon-frames-")
    audio_path = None
    files: list[WriteResult] = []
    try:
        frame_infos = extract_keyframes(
            input_path=source.local_path,
            output_dir=frames_dir,
            scene_threshold=config.video_scene_threshold,
            min_frames=config.video_scene_min_frames,
            fallback_fps=fps,
        )
        image_vectors = []
        image_core_rows = []
        derived_edges = []
        next_keyframe_edges = []
        image_ids: list[str] = []

        for idx, frame_info in enumerate(frame_infos):
            frame_path = frame_info.path
            with Image.open(frame_path) as img:
                rgb = img.convert("RGB")
                width, height = rgb.size
                vector = get_image_embedder(512).encode([rgb])[0]
                thumb_uri = None
                if config.video_thumbnail_width > 0:
                    thumb_uri = _thumbnail_uri(output_root, media_asset_id, idx)
                    _write_thumbnail(rgb, thumb_uri, config.video_thumbnail_width)
            image_vectors.append(vector)
            image_id = str(uuid.uuid4())
            image_ids.append(image_id)
            image_core_rows.append(
                {
                    "id": image_id,
                    "media_asset_id": media_asset_id,
                    "frame_index": idx,
                    "timestamp_ms": frame_info.timestamp_ms,
                    "width_px": width,
                    "height_px": height,
                    "thumbnail_uri": thumb_uri,
                    "embedding_model": _image_model(),
                    **tenancy_fields(
                        org_id=source.org_id,
                        site_id=source.site_id,
                        stream_id=source.stream_id,
                    ),
                    "pipeline_version": pipeline_version,
                    "schema_version": schema_version,
                }
            )
            derived_edges.append(
                {
                    "src_id": image_id,
                    "dst_id": media_asset_id,
                    "schema_version": schema_version,
                }
            )

        for idx in range(1, len(image_ids)):
            next_keyframe_edges.append(
                {
                    "src_id": image_ids[idx - 1],
                    "dst_id": image_ids[idx],
                    "schema_version": schema_version,
                }
            )

        transcript_core_rows = []
        transcript_text_rows = []
        transcript_vector_rows = []
        next_transcript_edges = []
        segment_ids: list[str] = []
        audio_clip_core = None
        audio_vector = None

        if probe.has_audio:
            audio_path = extract_audio(source.local_path)
            audio_bytes = Path(audio_path).read_bytes()
            audio_vector = get_audio_embedder(512).encode([audio_bytes])[0]
            segments = transcribe_audio(audio_path, probe.duration_seconds)
            text_vectors = get_text_embedder(768).encode(
                [segment.text for segment in segments]
            )

            audio_clip_id = str(uuid.uuid4())
            audio_clip_core = {
                "id": audio_clip_id,
                "media_asset_id": media_asset_id,
                "start_ms": 0,
                "end_ms": duration_ms,
                "sample_rate_hz": probe.audio_sample_rate or 48000,
                "channels": probe.audio_channels or 1,
                "embedding_model": _audio_model(),
                **tenancy_fields(
                    org_id=source.org_id,
                    site_id=source.site_id,
                    stream_id=source.stream_id,
                ),
                "pipeline_version": pipeline_version,
                "schema_version": schema_version,
            }
            derived_edges.append(
                {
                    "src_id": audio_clip_id,
                    "dst_id": media_asset_id,
                    "schema_version": schema_version,
                }
            )

            for segment, vector in zip(segments, text_vectors, strict=False):
                segment_id = str(uuid.uuid4())
                segment_ids.append(segment_id)
                transcript_core_rows.append(
                    {
                        "id": segment_id,
                        "media_asset_id": media_asset_id,
                        "segment_index": segment.index,
                        "start_ms": segment.start_ms,
                        "end_ms": segment.end_ms,
                        "language": segment.language,
                        "embedding_model": _text_model(),
                        **tenancy_fields(
                            org_id=source.org_id,
                            site_id=source.site_id,
                            stream_id=source.stream_id,
                        ),
                        "pipeline_version": pipeline_version,
                        "schema_version": schema_version,
                    }
                )
                transcript_text_rows.append({"content": segment.text})
                transcript_vector_rows.append({"text_embedding": vector})
                derived_edges.append(
                    {
                        "src_id": segment_id,
                        "dst_id": media_asset_id,
                        "schema_version": schema_version,
                    }
                )

            for idx in range(1, len(segment_ids)):
                next_transcript_edges.append(
                    {
                        "src_id": segment_ids[idx - 1],
                        "dst_id": segment_ids[idx],
                        "schema_version": schema_version,
                    }
                )

        files.append(
            write_parquet(
                [media_row],
                schema_for("MediaAsset", "core"),
                vertex_part_uri(output_root, "MediaAsset", "core", str(uuid.uuid4())),
            )
        )
        if image_core_rows:
            files.append(
                write_parquet(
                    image_core_rows,
                    schema_for("ImageAsset", "core"),
                    vertex_part_uri(
                        output_root, "ImageAsset", "core", str(uuid.uuid4())
                    ),
                )
            )
            files.append(
                write_parquet(
                    [{"clip_vector": vec} for vec in image_vectors],
                    schema_for("ImageAsset", "vector"),
                    vertex_part_uri(
                        output_root, "ImageAsset", "vector", str(uuid.uuid4())
                    ),
                )
            )
            if next_keyframe_edges:
                files.append(
                    write_parquet(
                        next_keyframe_edges,
                        schema_for("NextKeyframe", "adj_list"),
                        edge_part_uri(output_root, "NextKeyframe", str(uuid.uuid4())),
                    )
                )
        if transcript_core_rows:
            files.append(
                write_parquet(
                    transcript_core_rows,
                    schema_for("Transcript", "core"),
                    vertex_part_uri(
                        output_root, "Transcript", "core", str(uuid.uuid4())
                    ),
                )
            )
            files.append(
                write_parquet(
                    transcript_text_rows,
                    schema_for("Transcript", "text"),
                    vertex_part_uri(
                        output_root, "Transcript", "text", str(uuid.uuid4())
                    ),
                )
            )
            files.append(
                write_parquet(
                    transcript_vector_rows,
                    schema_for("Transcript", "vector"),
                    vertex_part_uri(
                        output_root, "Transcript", "vector", str(uuid.uuid4())
                    ),
                )
            )
            if next_transcript_edges:
                files.append(
                    write_parquet(
                        next_transcript_edges,
                        schema_for("NextTranscript", "adj_list"),
                        edge_part_uri(output_root, "NextTranscript", str(uuid.uuid4())),
                    )
                )
        if audio_clip_core and audio_vector:
            files.append(
                write_parquet(
                    [audio_clip_core],
                    schema_for("AudioClip", "core"),
                    vertex_part_uri(
                        output_root, "AudioClip", "core", str(uuid.uuid4())
                    ),
                )
            )
            files.append(
                write_parquet(
                    [{"clap_embedding": audio_vector}],
                    schema_for("AudioClip", "vector"),
                    vertex_part_uri(
                        output_root, "AudioClip", "vector", str(uuid.uuid4())
                    ),
                )
            )
        if derived_edges:
            files.append(
                write_parquet(
                    derived_edges,
                    schema_for("DerivedFrom", "adj_list"),
                    edge_part_uri(output_root, "DerivedFrom", str(uuid.uuid4())),
                )
            )

        completed_at = datetime.now(timezone.utc)
        run_id = str(uuid.uuid4())
        manifest = build_manifest(
            pipeline_version=pipeline_version,
            schema_version=schema_version,
            counts={
                "MediaAsset": 1,
                "ImageAsset": len(image_core_rows),
                "Transcript": len(transcript_core_rows),
                "AudioClip": 1 if audio_clip_core else 0,
                "DerivedFrom": len(derived_edges),
                "NextKeyframe": len(next_keyframe_edges),
                "NextTranscript": len(next_transcript_edges),
            },
            files=files,
            started_at=started_at,
            completed_at=completed_at,
        )
        manifest_path = manifest_uri(output_root, run_id)
        write_manifest(manifest, manifest_path)

        return PipelineResult(
            counts={
                "MediaAsset": 1,
                "ImageAsset": len(image_core_rows),
                "Transcript": len(transcript_core_rows),
                "AudioClip": 1 if audio_clip_core else 0,
                "DerivedFrom": len(derived_edges),
                "NextKeyframe": len(next_keyframe_edges),
                "NextTranscript": len(next_transcript_edges),
            },
            manifest_uri=manifest_path,
            media_asset_id=media_asset_id,
        )
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)
        if audio_path:
            cleanup_tmp(audio_path)
