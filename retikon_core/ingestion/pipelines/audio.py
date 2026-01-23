from __future__ import annotations

import uuid
from datetime import datetime, timezone

from retikon_core.config import Config
from retikon_core.embeddings.stub import get_audio_embedder, get_text_embedder
from retikon_core.errors import PermanentError
from retikon_core.ingestion.download import cleanup_tmp
from retikon_core.ingestion.media import normalize_audio, probe_media
from retikon_core.ingestion.pipelines.types import PipelineResult
from retikon_core.ingestion.transcribe import transcribe_audio
from retikon_core.ingestion.types import IngestSource
from retikon_core.storage.manifest import build_manifest, write_manifest
from retikon_core.storage.paths import (
    edge_part_uri,
    graph_root,
    manifest_uri,
    vertex_part_uri,
)
from retikon_core.storage.schemas import schema_for
from retikon_core.storage.writer import WriteResult, write_parquet


def _text_model() -> str:
    return "BAAI/bge-base-en-v1.5"


def _audio_model() -> str:
    return "laion/clap-htsat-fused"


def ingest_audio(
    *,
    source: IngestSource,
    config: Config,
    output_uri: str | None,
    pipeline_version: str,
    schema_version: str,
) -> PipelineResult:
    started_at = datetime.now(timezone.utc)
    probe = probe_media(source.local_path)
    if probe.duration_seconds > config.max_audio_seconds:
        raise PermanentError("Audio duration exceeds max")

    normalized_path = normalize_audio(source.local_path)
    try:
        audio_bytes = open(normalized_path, "rb").read()
        audio_vector = get_audio_embedder(512).encode([audio_bytes])[0]

        segments = transcribe_audio(normalized_path, probe.duration_seconds)
        texts = [segment.text for segment in segments]
        text_vectors = get_text_embedder(768).encode(texts)

        output_root = output_uri or graph_root(config.graph_bucket, config.graph_prefix)
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
            "created_at": now,
            "pipeline_version": pipeline_version,
            "schema_version": schema_version,
        }

        audio_clip_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{media_asset_id}:audio"))
        audio_clip_core = {
            "id": audio_clip_id,
            "media_asset_id": media_asset_id,
            "start_ms": 0,
            "end_ms": duration_ms,
            "sample_rate_hz": probe.audio_sample_rate or 48000,
            "channels": probe.audio_channels or 1,
            "embedding_model": _audio_model(),
            "pipeline_version": pipeline_version,
            "schema_version": schema_version,
        }

        transcript_core_rows = []
        transcript_text_rows = []
        transcript_vector_rows = []
        next_edges = []
        derived_edges = [{"src_id": audio_clip_id, "dst_id": media_asset_id}]

        for segment, vector in zip(segments, text_vectors, strict=False):
            segment_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{media_asset_id}:segment:{segment.index}",
                )
            )
            transcript_core_rows.append(
                {
                    "id": segment_id,
                    "media_asset_id": media_asset_id,
                    "segment_index": segment.index,
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                    "language": segment.language,
                    "embedding_model": _text_model(),
                    "pipeline_version": pipeline_version,
                    "schema_version": schema_version,
                }
            )
            transcript_text_rows.append({"content": segment.text})
            transcript_vector_rows.append({"text_embedding": vector})
            derived_edges.append({"src_id": segment_id, "dst_id": media_asset_id})
            if segment.index > 0:
                prev_id = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"{media_asset_id}:segment:{segment.index - 1}",
                    )
                )
                next_edges.append({"src_id": prev_id, "dst_id": segment_id})

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

        completed_at = datetime.now(timezone.utc)
        run_id = str(uuid.uuid4())
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

        return PipelineResult(
            counts={
                "MediaAsset": 1,
                "Transcript": len(transcript_core_rows),
                "AudioClip": 1,
                "DerivedFrom": len(derived_edges),
                "NextTranscript": len(next_edges),
            },
            manifest_uri=manifest_path,
        )
    finally:
        if normalized_path != source.local_path:
            cleanup_tmp(normalized_path)
