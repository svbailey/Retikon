from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone

from retikon_core.config import Config
from retikon_core.embeddings import get_audio_embedder, get_text_embedder
from retikon_core.embeddings.timeout import run_inference
from retikon_core.errors import PermanentError
from retikon_core.ingestion.download import cleanup_tmp
from retikon_core.ingestion.media import normalize_audio, probe_media
from retikon_core.ingestion.pipelines.types import PipelineResult
from retikon_core.ingestion.transcribe import transcribe_audio
from retikon_core.ingestion.types import IngestSource
from retikon_core.logging import get_logger
from retikon_core.storage.manifest import build_manifest, write_manifest
from retikon_core.storage.paths import (
    edge_part_uri,
    manifest_uri,
    vertex_part_uri,
)
from retikon_core.storage.schemas import schema_for
from retikon_core.storage.writer import WriteResult, write_parquet
from retikon_core.tenancy import tenancy_fields

logger = get_logger(__name__)


def _text_model() -> str:
    return os.getenv("TEXT_MODEL_NAME", "BAAI/bge-base-en-v1.5")


def _audio_model() -> str:
    return os.getenv("AUDIO_MODEL_NAME", "laion/clap-htsat-fused")


def _should_skip_normalize(
    source: IngestSource,
    probe,
    config: Config,
) -> bool:
    if not config.audio_skip_normalize_if_wav:
        return False
    local_path = source.local_path or ""
    if not local_path.lower().endswith(".wav"):
        return False
    if (probe.audio_sample_rate or 0) != 48000:
        return False
    if (probe.audio_channels or 0) != 1:
        return False
    return True


def ingest_audio(
    *,
    source: IngestSource,
    config: Config,
    output_uri: str | None,
    pipeline_version: str,
    schema_version: str,
) -> PipelineResult:
    timings: dict[str, float | int | str] = {}
    pipeline_start = time.monotonic()
    started_at = datetime.now(timezone.utc)
    probe_start = time.monotonic()
    probe = probe_media(source.local_path)
    timings["probe_ms"] = round((time.monotonic() - probe_start) * 1000.0, 2)
    if probe.duration_seconds > config.max_audio_seconds:
        raise PermanentError("Audio duration exceeds max")

    normalize_start = time.monotonic()
    if _should_skip_normalize(source, probe, config):
        normalized_path = source.local_path
        timings["normalize_ms"] = 0.0
        timings["normalize_skipped"] = True
    else:
        normalized_path = normalize_audio(source.local_path)
        timings["normalize_ms"] = round((time.monotonic() - normalize_start) * 1000.0, 2)
    try:
        read_start = time.monotonic()
        audio_bytes = open(normalized_path, "rb").read()
        timings["read_audio_ms"] = round(
            (time.monotonic() - read_start) * 1000.0, 2
        )
        embed_start = time.monotonic()
        audio_vector = run_inference(
            "audio",
            lambda: get_audio_embedder(512).encode([audio_bytes])[0],
        )
        timings["audio_embed_ms"] = round(
            (time.monotonic() - embed_start) * 1000.0, 2
        )

        segments = []
        transcribe_start = time.monotonic()
        if config.audio_transcribe:
            segments = transcribe_audio(normalized_path, probe.duration_seconds)
        if config.audio_max_segments > 0 and len(segments) > config.audio_max_segments:
            segments = segments[: config.audio_max_segments]
        timings["transcribe_ms"] = round(
            (time.monotonic() - transcribe_start) * 1000.0, 2
        )
        text_vectors: list[list[float]] = []
        if segments:
            text_embed_start = time.monotonic()
            texts = [segment.text for segment in segments]
            text_vectors = run_inference(
                "text",
                lambda: get_text_embedder(768).encode(texts),
            )
            timings["text_embed_ms"] = round(
                (time.monotonic() - text_embed_start) * 1000.0, 2
            )

        output_root = output_uri or config.graph_root_uri()
        media_asset_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        duration_ms = int(probe.duration_seconds * 1000.0)

        media_row = {
            "id": media_asset_id,
            "uri": source.uri,
            "media_type": "audio",
            "content_type": source.content_type or "application/octet-stream",
            "size_bytes": source.size_bytes or 0,
            "source_bucket": source.bucket,
            "source_object": source.name,
            "source_generation": source.generation,
            "checksum": source.md5_hash or source.crc32c,
            "duration_ms": duration_ms,
            "width_px": None,
            "height_px": None,
            "frame_count": None,
            "sample_rate_hz": probe.audio_sample_rate or 48000,
            "channels": probe.audio_channels or 1,
            **tenancy_fields(
                org_id=source.org_id,
                site_id=source.site_id,
                stream_id=source.stream_id,
            ),
            "created_at": now,
            "pipeline_version": pipeline_version,
            "schema_version": schema_version,
        }

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

        transcript_core_rows = []
        transcript_text_rows = []
        transcript_vector_rows = []
        next_edges = []
        segment_ids: list[str] = []
        derived_edges = [
            {
                "src_id": audio_clip_id,
                "dst_id": media_asset_id,
                "schema_version": schema_version,
            }
        ]

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
            next_edges.append(
                {
                    "src_id": segment_ids[idx - 1],
                    "dst_id": segment_ids[idx],
                    "schema_version": schema_version,
                }
            )

        write_start = time.monotonic()
        files: list[WriteResult] = []
        files.append(
            write_parquet(
                [media_row],
                schema_for("MediaAsset", "core"),
                vertex_part_uri(output_root, "MediaAsset", "core", str(uuid.uuid4())),
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
            if next_edges:
                files.append(
                    write_parquet(
                        next_edges,
                        schema_for("NextTranscript", "adj_list"),
                        edge_part_uri(output_root, "NextTranscript", str(uuid.uuid4())),
                    )
                )

        files.append(
            write_parquet(
                [audio_clip_core],
                schema_for("AudioClip", "core"),
                vertex_part_uri(output_root, "AudioClip", "core", str(uuid.uuid4())),
            )
        )
        files.append(
            write_parquet(
                [{"clap_embedding": audio_vector}],
                schema_for("AudioClip", "vector"),
                vertex_part_uri(output_root, "AudioClip", "vector", str(uuid.uuid4())),
            )
        )
        files.append(
            write_parquet(
                derived_edges,
                schema_for("DerivedFrom", "adj_list"),
                edge_part_uri(output_root, "DerivedFrom", str(uuid.uuid4())),
            )
        )
        timings["write_ms"] = round((time.monotonic() - write_start) * 1000.0, 2)

        completed_at = datetime.now(timezone.utc)
        run_id = str(uuid.uuid4())
        manifest_start = time.monotonic()
        manifest = build_manifest(
            pipeline_version=pipeline_version,
            schema_version=schema_version,
            counts={
                "MediaAsset": 1,
                "Transcript": len(transcript_core_rows),
                "AudioClip": 1,
                "DerivedFrom": len(derived_edges),
                "NextTranscript": len(next_edges),
            },
            files=files,
            started_at=started_at,
            completed_at=completed_at,
        )
        manifest_path = manifest_uri(output_root, run_id)
        write_manifest(manifest, manifest_path)
        timings["manifest_ms"] = round(
            (time.monotonic() - manifest_start) * 1000.0, 2
        )

        if config.audio_profile:
            timings["media_asset_id"] = media_asset_id
            timings["duration_ms"] = duration_ms
            timings["segments"] = len(segments)
            timings["total_ms"] = round(
                (time.monotonic() - pipeline_start) * 1000.0,
                2,
            )
            logger.info("Audio pipeline profile", extra=timings)

        return PipelineResult(
            counts={
                "MediaAsset": 1,
                "Transcript": len(transcript_core_rows),
                "AudioClip": 1,
                "DerivedFrom": len(derived_edges),
                "NextTranscript": len(next_edges),
            },
            manifest_uri=manifest_path,
            media_asset_id=media_asset_id,
            duration_ms=duration_ms,
        )
    finally:
        if normalized_path != source.local_path:
            cleanup_tmp(normalized_path)
