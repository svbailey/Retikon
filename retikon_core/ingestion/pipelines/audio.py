from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone

from retikon_core.config import Config
from retikon_core.embeddings import (
    get_audio_embedder,
    get_embedding_artifact,
    get_runtime_embedding_backend,
    get_text_embedder,
)
from retikon_core.embeddings.timeout import run_inference
from retikon_core.errors import PermanentError
from retikon_core.ingestion.download import cleanup_tmp
from retikon_core.ingestion.media import analyze_audio, normalize_audio, probe_media
from retikon_core.ingestion.pipelines.metrics import (
    CallTracker,
    StageTimer,
    build_stage_timings,
    timed_call,
)
from retikon_core.ingestion.pipelines.types import PipelineResult
from retikon_core.ingestion.transcription_policy import (
    resolve_transcribe_policy,
    transcribe_limit_reason,
)
from retikon_core.ingestion.transcribe import (
    resolve_transcribe_model_name,
    transcribe_audio,
)
from retikon_core.ingestion.types import IngestSource
from retikon_core.logging import get_logger
from retikon_core.storage.manifest import (
    build_manifest,
    manifest_bytes,
    manifest_metrics_subset,
    write_manifest,
)
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
    timer = StageTimer()
    calls = CallTracker()
    pipeline_start = time.monotonic()
    started_at = datetime.now(timezone.utc)
    with timer.track("probe"):
        probe = probe_media(source.local_path)
    if probe.duration_seconds > config.max_audio_seconds:
        raise PermanentError("Audio duration exceeds max")

    if _should_skip_normalize(source, probe, config):
        normalized_path = source.local_path
        normalize_skipped = True
    else:
        normalize_skipped = False
        with timer.track("normalize"):
            normalized_path = normalize_audio(source.local_path)
    try:
        audio_duration_ms = int(probe.duration_seconds * 1000.0)
        extracted_audio_duration_ms = audio_duration_ms
        trimmed_silence_ms = 0
        transcribed_ms = 0
        transcript_language = None
        transcript_error_reason = ""
        transcribe_tier = config.transcribe_tier
        transcribe_enabled = config.audio_transcribe and transcribe_tier != "off"
        transcribe_policy = resolve_transcribe_policy(config, source)
        transcribe_max_ms = transcribe_policy.max_ms
        transcript_model_tier = transcribe_tier if transcribe_enabled else "off"
        audio_has_speech = True
        if config.audio_transcribe and config.audio_vad_enabled:
            with timer.track("vad"):
                analysis = analyze_audio(
                    normalized_path,
                    frame_ms=config.audio_vad_frame_ms,
                    silence_db=config.audio_vad_silence_db,
                    min_speech_ms=config.audio_vad_min_speech_ms,
                )
            audio_duration_ms = analysis.duration_ms
            extracted_audio_duration_ms = analysis.duration_ms
            trimmed_silence_ms = analysis.silence_ms
            audio_has_speech = analysis.has_speech
        with timer.track("read_audio"):
            audio_bytes = open(normalized_path, "rb").read()
        with timer.track("audio_embed"):
            audio_vector = timed_call(
                calls,
                "audio_embed",
                lambda: run_inference(
                    "audio",
                    lambda: get_audio_embedder(512).encode([audio_bytes])[0],
                ),
            )

        segments = []
        transcript_status = "skipped_by_policy"
        if transcribe_enabled:
            if not probe.has_audio:
                transcript_status = "no_audio_track"
            elif not audio_has_speech:
                transcript_status = "no_speech"
            elif transcribe_max_ms > 0 and extracted_audio_duration_ms > transcribe_max_ms:
                transcript_status = "skipped_by_policy"
                transcript_error_reason = transcribe_limit_reason(
                    transcribe_policy.source
                )
            else:
                calls.set_context(
                    "transcribe",
                    {
                        "tier": transcript_model_tier,
                        "model_id": resolve_transcribe_model_name(transcribe_tier),
                    },
                )
                with timer.track("transcribe"):
                    segments = timed_call(
                        calls,
                        "transcribe",
                        lambda: transcribe_audio(
                            normalized_path,
                            probe.duration_seconds,
                            tier=transcribe_tier,
                        ),
                    )
                if segments:
                    transcript_status = "ok"
                    transcribed_ms = extracted_audio_duration_ms
                else:
                    transcript_status = "failed"
                    transcript_error_reason = "empty_transcript"
        elif config.audio_transcribe:
            transcript_error_reason = "transcribe_disabled"
        if config.audio_max_segments > 0 and len(segments) > config.audio_max_segments:
            segments = segments[: config.audio_max_segments]
        text_vectors: list[list[float]] = []
        if segments:
            transcript_language = segments[0].language if segments[0].language else None
            with timer.track("text_embed"):
                texts = [segment.text for segment in segments]
                text_vectors = timed_call(
                    calls,
                    "text_embed",
                    lambda: run_inference(
                        "text",
                        lambda: get_text_embedder(768).encode(texts),
                    ),
                )

        output_root = output_uri or config.graph_root_uri()
        media_asset_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        duration_ms = int(probe.duration_seconds * 1000.0)
        audio_embedding_backend = None
        audio_embedding_artifact = None
        text_embedding_backend = None
        text_embedding_artifact = None
        if config.embedding_metadata_enabled:
            audio_embedding_backend = get_runtime_embedding_backend("audio")
            audio_embedding_artifact = get_embedding_artifact("audio")
            text_embedding_backend = get_runtime_embedding_backend("text")
            text_embedding_artifact = get_embedding_artifact("text")

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
            "embedding_backend": audio_embedding_backend,
            "embedding_artifact": audio_embedding_artifact,
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
                    "embedding_backend": text_embedding_backend,
                    "embedding_artifact": text_embedding_artifact,
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

        files: list[WriteResult] = []
        with timer.track("write_parquet"):
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

        parquet_bytes_preview = sum(item.bytes_written for item in files)
        bytes_raw_preview = source.size_bytes or 0
        transcript_word_count_preview = sum(
            len(segment.text.split()) for segment in segments if segment.text
        )
        hashes_preview: dict[str, str] = {}
        if source.content_hash_sha256:
            hashes_preview["content_sha256"] = source.content_hash_sha256
        raw_timings_preview = timer.summary()
        stage_timings_preview = build_stage_timings(
            raw_timings_preview,
            {
                "probe": "decode_ms",
                "normalize": "decode_ms",
                "read_audio": "decode_ms",
                "vad": "vad_ms",
                "audio_embed": "embed_audio_ms",
                "transcribe": "transcribe_ms",
                "text_embed": "embed_text_ms",
                "write_parquet": "write_parquet_ms",
                "write_manifest": "write_manifest_ms",
            },
        )
        manifest_metrics = manifest_metrics_subset(
            {
                "io": {
                    "bytes_raw": bytes_raw_preview,
                    "bytes_parquet": parquet_bytes_preview,
                    "bytes_derived": parquet_bytes_preview,
                },
                "quality": {
                    "transcript_status": transcript_status,
                    "transcript_model_tier": transcript_model_tier,
                    "transcript_word_count": transcript_word_count_preview,
                    "transcript_segment_count": len(transcript_core_rows),
                    "normalize_skipped": normalize_skipped,
                    "audio_duration_ms": audio_duration_ms,
                    "extracted_audio_duration_ms": extracted_audio_duration_ms,
                    "trimmed_silence_ms": trimmed_silence_ms,
                    "transcribed_ms": transcribed_ms,
                    "transcript_language": transcript_language,
                    "transcript_error_reason": transcript_error_reason,
                },
                "hashes": hashes_preview,
                "embeddings": {
                    "audio": {
                        "count": 1,
                        "dims": 512,
                    },
                    "text": {
                        "count": len(transcript_core_rows),
                        "dims": 768,
                    },
                },
                "evidence": {
                    "frames": 0,
                    "snippets": 0,
                    "segments": len(transcript_core_rows),
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
                    "Transcript": len(transcript_core_rows),
                    "AudioClip": 1,
                    "DerivedFrom": len(derived_edges),
                    "NextTranscript": len(next_edges),
                },
                files=files,
                started_at=started_at,
                completed_at=completed_at,
                metrics=manifest_metrics,
            )
            manifest_size = manifest_bytes(manifest, compact=False)
            manifest_path = manifest_uri(output_root, run_id)
            write_manifest(manifest, manifest_path)

        parquet_bytes = sum(item.bytes_written for item in files)
        bytes_raw = source.size_bytes or 0
        transcript_word_count = sum(
            len(segment.text.split()) for segment in segments if segment.text
        )
        hashes: dict[str, str] = {}
        if source.content_hash_sha256:
            hashes["content_sha256"] = source.content_hash_sha256
        raw_timings = timer.summary()
        stage_timings_ms = build_stage_timings(
            raw_timings,
            {
                "probe": "decode_ms",
                "normalize": "decode_ms",
                "read_audio": "decode_ms",
                "vad": "vad_ms",
                "audio_embed": "embed_audio_ms",
                "transcribe": "transcribe_ms",
                "text_embed": "embed_text_ms",
                "write_parquet": "write_parquet_ms",
                "write_manifest": "write_manifest_ms",
            },
        )
        derived_breakdown = {
            "manifest_b": manifest_size,
            "parquet_b": parquet_bytes,
            "thumbnails_b": 0,
            "frames_b": 0,
            "transcript_b": 0,
            "embeddings_b": 0,
            "other_b": 0,
        }
        derived_total = sum(derived_breakdown.values())
        metrics = {
            "timings_ms": raw_timings,
            "stage_timings_ms": stage_timings_ms,
            "pipe_ms": round(sum(stage_timings_ms.values()), 2),
            "model_calls": calls.summary(),
            "io": {
                "bytes_raw": bytes_raw,
                "bytes_parquet": parquet_bytes,
                "bytes_derived": parquet_bytes,
                "bytes_manifest": manifest_size,
                "derived_b_total": derived_total,
                "derived_b_breakdown": derived_breakdown,
            },
            "quality": {
                "transcript_status": transcript_status,
                "transcript_model_tier": transcript_model_tier,
                "transcript_word_count": transcript_word_count,
                "transcript_segment_count": len(transcript_core_rows),
                "normalize_skipped": normalize_skipped,
                "audio_duration_ms": audio_duration_ms,
                "extracted_audio_duration_ms": extracted_audio_duration_ms,
                "trimmed_silence_ms": trimmed_silence_ms,
                "transcribed_ms": transcribed_ms,
                "transcript_language": transcript_language,
                "transcript_error_reason": transcript_error_reason,
            },
            "hashes": hashes,
            "embeddings": {
                "audio": {
                    "count": 1,
                    "dims": 512,
                },
                "text": {
                    "count": len(transcript_core_rows),
                    "dims": 768,
                },
            },
            "evidence": {
                "frames": 0,
                "snippets": 0,
                "segments": len(transcript_core_rows),
            },
        }

        if config.audio_profile:
            profile = timer.summary()
            profile["media_asset_id"] = media_asset_id
            profile["duration_ms"] = duration_ms
            profile["segments"] = len(segments)
            profile["total_ms"] = round(
                (time.monotonic() - pipeline_start) * 1000.0,
                2,
            )
            logger.info("Audio pipeline profile", extra=profile)

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
            metrics=metrics,
        )
    finally:
        if normalized_path != source.local_path:
            cleanup_tmp(normalized_path)
