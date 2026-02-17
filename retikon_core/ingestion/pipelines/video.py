from __future__ import annotations

import os
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import fsspec
from PIL import Image

from retikon_core.config import Config
from retikon_core.embeddings import (
    get_audio_embedder,
    get_embedding_artifact,
    get_image_embedder,
    get_runtime_embedding_backend,
    get_text_embedder,
)
from retikon_core.embeddings.timeout import run_inference
from retikon_core.errors import InferenceTimeoutError, PermanentError
from retikon_core.ingestion.download import cleanup_tmp
from retikon_core.ingestion.media import (
    analyze_audio,
    extract_audio,
    extract_keyframes,
    probe_media,
)
from retikon_core.ingestion.pipelines.metrics import (
    CallTracker,
    StageTimer,
    build_stage_timings,
    timed_call,
)
from retikon_core.ingestion.pipelines.audio_segments import extract_audio_windows
from retikon_core.ingestion.pipelines.embedding_utils import (
    image_embed_batch_size,
    prepare_video_image_for_embed,
    thumbnail_jpeg_quality,
    video_embed_max_dim,
)
from retikon_core.ingestion.ocr import ocr_result_from_image
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
from retikon_core.storage.manifest import (
    build_manifest,
    manifest_bytes,
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


def _text_model() -> str:
    return os.getenv("TEXT_MODEL_NAME", "BAAI/bge-base-en-v1.5")


def _image_model() -> str:
    return os.getenv("IMAGE_MODEL_NAME", "openai/clip-vit-base-patch32")


def _audio_model() -> str:
    return os.getenv("AUDIO_MODEL_NAME", "laion/clap-htsat-fused")


def _resolve_fps(config: Config, duration_seconds: float) -> float:
    if config.video_sample_interval_seconds > 0:
        base_interval = float(config.video_sample_interval_seconds)
    elif config.video_sample_fps > 0:
        base_interval = 1.0 / float(config.video_sample_fps)
    else:
        base_interval = 1.0
    effective_interval = base_interval
    if duration_seconds > 0 and config.max_frames_per_video > 0:
        budget_interval = duration_seconds / float(config.max_frames_per_video)
        effective_interval = max(effective_interval, budget_interval)
        if effective_interval > duration_seconds:
            effective_interval = duration_seconds
    if effective_interval <= 0:
        effective_interval = base_interval if base_interval > 0 else 1.0
    return 1.0 / effective_interval


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
) -> int:
    if width <= 0:
        return 0
    thumb = image.copy()
    if thumb.width > width:
        height = max(1, int(thumb.height * (width / float(thumb.width))))
        thumb = thumb.resize((width, height))
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        thumb.save(tmp_path, format="JPEG", quality=thumbnail_jpeg_quality())
        bytes_written = os.path.getsize(tmp_path)
        fs, path = fsspec.core.url_to_fs(uri)
        fs.makedirs(os.path.dirname(path), exist_ok=True)
        with fs.open(path, "wb") as handle, open(tmp_path, "rb") as src:
            shutil.copyfileobj(src, handle)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return bytes_written


def _sample_positions(total: int, limit: int) -> list[int]:
    if total <= 0 or limit <= 0:
        return []
    if total <= limit:
        return list(range(total))
    if limit == 1:
        return [0]
    step = (total - 1) / float(limit - 1)
    positions: list[int] = []
    seen: set[int] = set()
    for idx in range(limit):
        pos = int(round(idx * step))
        pos = max(0, min(total - 1, pos))
        if pos in seen:
            continue
        seen.add(pos)
        positions.append(pos)
    if len(positions) < limit:
        for pos in range(total):
            if pos in seen:
                continue
            positions.append(pos)
            if len(positions) >= limit:
                break
    return positions


def ingest_video(
    *,
    source: IngestSource,
    config: Config,
    output_uri: str | None,
    pipeline_version: str,
    schema_version: str,
) -> PipelineResult:
    started_at = datetime.now(timezone.utc)
    timer = StageTimer()
    calls = CallTracker()
    with timer.track("probe"):
        probe = probe_media(source.local_path)
    if probe.duration_seconds > config.max_video_seconds:
        raise PermanentError("Video duration exceeds max")

    output_root = output_uri or config.graph_root_uri()
    media_asset_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    duration_ms = int(probe.duration_seconds * 1000.0)
    audio_duration_ms = duration_ms if probe.has_audio else 0
    extracted_audio_duration_ms = 0
    trimmed_silence_ms = 0
    transcribed_ms = 0
    transcript_language = None
    transcript_error_reason = ""
    transcribe_tier = config.transcribe_tier
    transcribe_enabled = config.audio_transcribe and transcribe_tier != "off"
    transcribe_policy = resolve_transcribe_policy(config, source)
    transcribe_max_ms = transcribe_policy.max_ms
    transcript_model_tier = transcribe_tier if transcribe_enabled else "off"
    fps = _resolve_fps(config, probe.duration_seconds)
    image_embedding_backend = None
    image_embedding_artifact = None
    audio_embedding_backend = None
    audio_embedding_artifact = None
    text_embedding_backend = None
    text_embedding_artifact = None
    if config.embedding_metadata_enabled:
        image_embedding_backend = get_runtime_embedding_backend("image")
        image_embedding_artifact = get_embedding_artifact("image")
        audio_embedding_backend = get_runtime_embedding_backend("audio")
        audio_embedding_artifact = get_embedding_artifact("audio")
        text_embedding_backend = get_runtime_embedding_backend("text")
        text_embedding_artifact = get_embedding_artifact("text")

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
    thumbnail_bytes = 0
    try:
        with timer.track("extract_keyframes"):
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
        image_id_by_frame_index: dict[int, str] = {}

        embedder = get_image_embedder(512)
        batch_size = image_embed_batch_size()
        calls.set_context(
            "image_embed",
            {
                "batch_size": batch_size,
                "backend": get_runtime_embedding_backend("image"),
                "max_dim": video_embed_max_dim(),
            },
        )

        for batch_start in range(0, len(frame_infos), batch_size):
            batch_infos = frame_infos[batch_start : batch_start + batch_size]
            batch_images: list[Image.Image] = []
            batch_meta: list[tuple[int, object, int, int, Image.Image | None]] = []
            for idx_offset, frame_info in enumerate(batch_infos):
                idx = batch_start + idx_offset
                with Image.open(frame_info.path) as img:
                    rgb = img.convert("RGB")
                    width, height = rgb.size
                    embed_image = prepare_video_image_for_embed(rgb)
                    thumb_source = rgb if config.video_thumbnail_width > 0 else None
                    batch_images.append(embed_image)
                    batch_meta.append((idx, frame_info, width, height, thumb_source))
            if not batch_images:
                continue
            with timer.track("image_embed"):
                vectors = timed_call(
                    calls,
                    "image_embed",
                    lambda batch=batch_images: run_inference(
                        "image",
                        lambda batch=batch: embedder.encode(batch),
                    ),
                )
            if len(vectors) != len(batch_meta):
                raise PermanentError("Image embedding count mismatch")

            for (idx, frame_info, width, height, thumb_source), vector in zip(
                batch_meta,
                vectors,
                strict=False,
            ):
                thumb_uri = None
                if thumb_source is not None:
                    thumb_uri = _thumbnail_uri(output_root, media_asset_id, idx)
                    with timer.track("write_thumbnail"):
                        thumbnail_bytes += _write_thumbnail(
                            thumb_source,
                            thumb_uri,
                            config.video_thumbnail_width,
                        )
                image_vectors.append(vector)
                image_id = str(uuid.uuid4())
                image_ids.append(image_id)
                image_id_by_frame_index[idx] = image_id
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
                        "embedding_backend": image_embedding_backend,
                        "embedding_artifact": image_embedding_artifact,
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

        ocr_chunk_core_rows: list[dict[str, object]] = []
        ocr_chunk_text_rows: list[dict[str, object]] = []
        ocr_chunk_vector_rows: list[dict[str, object]] = []
        ocr_candidates = 0
        ocr_processed = 0
        ocr_status = "disabled"
        if config.ocr_keyframes and frame_infos and image_id_by_frame_index:
            selected_positions = _sample_positions(
                len(frame_infos),
                config.ocr_max_keyframes if config.ocr_max_keyframes > 0 else len(frame_infos),
            )
            ocr_candidates = len(selected_positions)
            ocr_items: list[tuple[str, int | None, int | None, str]] = []
            ocr_status = "empty"
            budget_start = time.monotonic()
            for pos in selected_positions:
                source_ref_id = image_id_by_frame_index.get(pos)
                if source_ref_id is None:
                    continue
                elapsed_ms = (time.monotonic() - budget_start) * 1000.0
                if config.ocr_total_budget_ms > 0 and elapsed_ms >= float(config.ocr_total_budget_ms):
                    if ocr_items:
                        ocr_status = "partial_budget"
                    else:
                        ocr_status = "budget_exhausted"
                    break
                frame_info = frame_infos[pos]
                try:
                    with Image.open(frame_info.path) as frame_image:
                        rgb = frame_image.convert("RGB")
                except Exception:
                    continue
                try:
                    with timer.track("ocr"):
                        ocr_result = run_inference(
                            "ocr",
                            lambda: ocr_result_from_image(
                                rgb,
                                min_confidence=config.ocr_min_confidence,
                                min_text_len=config.ocr_min_text_len,
                            ),
                        )
                except (InferenceTimeoutError, PermanentError):
                    continue
                except Exception:
                    continue
                ocr_processed += 1
                if not ocr_result.text:
                    continue
                ocr_items.append(
                    (
                        source_ref_id,
                        frame_info.timestamp_ms,
                        ocr_result.conf_avg,
                        ocr_result.text,
                    )
                )
            if ocr_items:
                with timer.track("ocr_text_embed"):
                    ocr_vectors = run_inference(
                        "text",
                        lambda: get_text_embedder(768).encode(
                            [item[3] for item in ocr_items]
                        ),
                    )
                for chunk_index, (item, vector) in enumerate(
                    zip(ocr_items, ocr_vectors, strict=False)
                ):
                    source_ref_id, source_time_ms, conf_avg, text = item
                    chunk_id = str(uuid.uuid4())
                    token_count = len([token for token in text.split() if token.strip()])
                    ocr_chunk_core_rows.append(
                        {
                            "id": chunk_id,
                            "media_asset_id": media_asset_id,
                            "chunk_index": chunk_index,
                            "char_start": 0,
                            "char_end": len(text),
                            "token_start": 0,
                            "token_end": token_count,
                            "token_count": token_count,
                            "source_type": "keyframe",
                            "source_ref_id": source_ref_id,
                            "source_time_ms": source_time_ms,
                            "ocr_conf_avg": conf_avg,
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
                    ocr_chunk_text_rows.append({"content": text})
                    ocr_chunk_vector_rows.append({"text_vector": vector})
                    derived_edges.append(
                        {
                            "src_id": chunk_id,
                            "dst_id": media_asset_id,
                            "schema_version": schema_version,
                        }
                    )
                if ocr_status == "empty":
                    ocr_status = "ok"

        transcript_core_rows = []
        transcript_text_rows = []
        transcript_vector_rows = []
        next_transcript_edges = []
        segment_ids: list[str] = []
        audio_clip_core = None
        audio_vector = None
        audio_segment_core_rows = []
        audio_segment_vector_rows = []
        audio_segment_candidates = 0
        audio_segment_silence_skipped = 0

        segments = []
        text_vectors: list[list[float]] = []
        transcript_status = "skipped_by_policy"
        if probe.has_audio:
            with timer.track("extract_audio"):
                audio_path = extract_audio(source.local_path)
                audio_bytes = Path(audio_path).read_bytes()
            if config.audio_transcribe and config.audio_vad_enabled:
                with timer.track("vad"):
                    analysis = analyze_audio(
                        audio_path,
                        frame_ms=config.audio_vad_frame_ms,
                        silence_db=config.audio_vad_silence_db,
                        min_speech_ms=config.audio_vad_min_speech_ms,
                    )
                extracted_audio_duration_ms = analysis.duration_ms
                trimmed_silence_ms = analysis.silence_ms
                audio_duration_ms = max(audio_duration_ms, analysis.duration_ms)
                audio_has_speech = analysis.has_speech
            else:
                audio_has_speech = True
                extracted_audio_duration_ms = audio_duration_ms
            if not transcribe_enabled:
                transcript_status = "skipped_by_policy"
                if config.audio_transcribe:
                    transcript_error_reason = "transcribe_disabled"
            elif not audio_has_speech:
                transcript_status = "no_speech"
            elif transcribe_max_ms > 0 and extracted_audio_duration_ms > transcribe_max_ms:
                transcript_status = "skipped_by_policy"
                transcript_error_reason = transcribe_limit_reason(
                    transcribe_policy.source
                )
            else:
                transcript_status = "ok"
            audio_embedder = get_audio_embedder(512)
            with timer.track("audio_embed"):
                audio_vector = timed_call(
                    calls,
                    "audio_embed",
                    lambda: run_inference(
                        "audio",
                        lambda: audio_embedder.encode([audio_bytes])[0],
                    ),
                )
            audio_window_batch = extract_audio_windows(
                path=audio_path,
                window_s=config.audio_segment_window_s,
                hop_s=config.audio_segment_hop_s,
                max_segments=config.audio_segment_max_segments,
                silence_db=config.audio_vad_silence_db,
            )
            audio_segment_candidates = audio_window_batch.candidate_count
            audio_segment_silence_skipped = audio_window_batch.skipped_silence_count
            if audio_window_batch.windows:
                with timer.track("audio_embed"):
                    segment_vectors = timed_call(
                        calls,
                        "audio_segment_embed",
                        lambda: run_inference(
                            "audio",
                            lambda: audio_embedder.encode(
                                [
                                    window.audio_bytes
                                    for window in audio_window_batch.windows
                                ]
                            ),
                        ),
                    )
                for window, vector in zip(
                    audio_window_batch.windows,
                    segment_vectors,
                    strict=False,
                ):
                    segment_id = str(uuid.uuid4())
                    audio_segment_core_rows.append(
                        {
                            "id": segment_id,
                            "media_asset_id": media_asset_id,
                            "start_ms": window.start_ms,
                            "end_ms": window.end_ms,
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
                    )
                    audio_segment_vector_rows.append({"clap_embedding": vector})
            if (
                transcribe_enabled
                and audio_has_speech
                and (transcribe_max_ms <= 0 or extracted_audio_duration_ms <= transcribe_max_ms)
            ):
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
                            audio_path,
                            probe.duration_seconds,
                            tier=transcribe_tier,
                        ),
                    )
                if segments:
                    transcribed_ms = extracted_audio_duration_ms or audio_duration_ms
                else:
                    transcript_status = "failed"
                    transcript_error_reason = "empty_transcript"
            if segments:
                transcript_language = segments[0].language if segments[0].language else None
                with timer.track("text_embed"):
                    text_vectors = timed_call(
                        calls,
                        "text_embed",
                        lambda: run_inference(
                            "text",
                            lambda: get_text_embedder(768).encode(
                                [segment.text for segment in segments]
                            ),
                        ),
                    )

            if audio_vector is not None:
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
                derived_edges.append(
                    {
                        "src_id": audio_clip_id,
                        "dst_id": media_asset_id,
                        "schema_version": schema_version,
                    }
                )
                for segment_row in audio_segment_core_rows:
                    derived_edges.append(
                        {
                            "src_id": segment_row["id"],
                            "dst_id": media_asset_id,
                            "schema_version": schema_version,
                        }
                    )
        else:
            transcript_status = "no_audio_track"

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
                next_transcript_edges.append(
                    {
                        "src_id": segment_ids[idx - 1],
                        "dst_id": segment_ids[idx],
                        "schema_version": schema_version,
                    }
                )

        with timer.track("write_parquet"):
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
            if audio_segment_core_rows:
                files.append(
                    write_parquet(
                        audio_segment_core_rows,
                        schema_for("AudioSegment", "core"),
                        vertex_part_uri(
                            output_root, "AudioSegment", "core", str(uuid.uuid4())
                        ),
                    )
                )
                files.append(
                    write_parquet(
                        audio_segment_vector_rows,
                        schema_for("AudioSegment", "vector"),
                        vertex_part_uri(
                            output_root, "AudioSegment", "vector", str(uuid.uuid4())
                        ),
                    )
                )
            if ocr_chunk_core_rows:
                files.append(
                    write_parquet(
                        ocr_chunk_core_rows,
                        schema_for("DocChunk", "core"),
                        vertex_part_uri(output_root, "DocChunk", "core", str(uuid.uuid4())),
                    )
                )
                files.append(
                    write_parquet(
                        ocr_chunk_text_rows,
                        schema_for("DocChunk", "text"),
                        vertex_part_uri(output_root, "DocChunk", "text", str(uuid.uuid4())),
                    )
                )
                files.append(
                    write_parquet(
                        ocr_chunk_vector_rows,
                        schema_for("DocChunk", "vector"),
                        vertex_part_uri(
                            output_root,
                            "DocChunk",
                            "vector",
                            str(uuid.uuid4()),
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
                "extract_keyframes": "extract_frames_ms",
                "image_embed": "embed_image_ms",
                "ocr": "decode_ms",
                "ocr_text_embed": "embed_text_ms",
                "write_thumbnail": "write_blobs_ms",
                "extract_audio": "extract_audio_ms",
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
                    "bytes_thumbnails": thumbnail_bytes,
                    "bytes_derived": parquet_bytes_preview + thumbnail_bytes,
                },
                "quality": {
                    "transcript_status": transcript_status,
                    "transcript_model_tier": transcript_model_tier,
                    "transcript_word_count": transcript_word_count_preview,
                    "transcript_segment_count": len(transcript_core_rows),
                    "audio_duration_ms": audio_duration_ms,
                    "extracted_audio_duration_ms": extracted_audio_duration_ms,
                    "trimmed_silence_ms": trimmed_silence_ms,
                    "transcribed_ms": transcribed_ms,
                    "transcript_language": transcript_language,
                    "transcript_error_reason": transcript_error_reason,
                    "ocr_status": ocr_status,
                    "ocr_candidates": ocr_candidates,
                    "ocr_processed": ocr_processed,
                    "ocr_snippet_count": len(ocr_chunk_core_rows),
                    "audio_segment_count": len(audio_segment_core_rows),
                    "audio_segment_candidates": audio_segment_candidates,
                    "audio_segment_silence_skipped": audio_segment_silence_skipped,
                },
                "hashes": hashes_preview,
                "embeddings": {
                    "image": {
                        "count": len(image_core_rows),
                        "dims": 512,
                    },
                    "audio": {
                        "count": (
                            (1 if audio_vector is not None else 0)
                            + len(audio_segment_core_rows)
                        ),
                        "dims": 512,
                    },
                    "text": {
                        "count": len(transcript_core_rows) + len(ocr_chunk_core_rows),
                        "dims": 768,
                    },
                },
                "evidence": {
                    "frames": len(image_core_rows),
                    "snippets": len(ocr_chunk_core_rows),
                    "segments": len(transcript_core_rows) + len(audio_segment_core_rows),
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
                    "ImageAsset": len(image_core_rows),
                    "DocChunk": len(ocr_chunk_core_rows),
                    "Transcript": len(transcript_core_rows),
                    "AudioClip": 1 if audio_clip_core else 0,
                    "AudioSegment": len(audio_segment_core_rows),
                    "DerivedFrom": len(derived_edges),
                    "NextKeyframe": len(next_keyframe_edges),
                    "NextTranscript": len(next_transcript_edges),
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
                "extract_keyframes": "extract_frames_ms",
                "image_embed": "embed_image_ms",
                "ocr": "decode_ms",
                "ocr_text_embed": "embed_text_ms",
                "write_thumbnail": "write_blobs_ms",
                "extract_audio": "extract_audio_ms",
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
            "thumbnails_b": thumbnail_bytes,
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
                "bytes_thumbnails": thumbnail_bytes,
                "bytes_derived": parquet_bytes + thumbnail_bytes,
                "bytes_manifest": manifest_size,
                "derived_b_total": derived_total,
                "derived_b_breakdown": derived_breakdown,
            },
            "quality": {
                "transcript_status": transcript_status,
                "transcript_model_tier": transcript_model_tier,
                "transcript_word_count": transcript_word_count,
                "transcript_segment_count": len(transcript_core_rows),
                "audio_duration_ms": audio_duration_ms,
                "extracted_audio_duration_ms": extracted_audio_duration_ms,
                "trimmed_silence_ms": trimmed_silence_ms,
                "transcribed_ms": transcribed_ms,
                "transcript_language": transcript_language,
                "transcript_error_reason": transcript_error_reason,
                "ocr_status": ocr_status,
                "ocr_candidates": ocr_candidates,
                "ocr_processed": ocr_processed,
                "ocr_snippet_count": len(ocr_chunk_core_rows),
                "audio_segment_count": len(audio_segment_core_rows),
                "audio_segment_candidates": audio_segment_candidates,
                "audio_segment_silence_skipped": audio_segment_silence_skipped,
            },
            "hashes": hashes,
            "embeddings": {
                "image": {
                    "count": len(image_core_rows),
                    "dims": 512,
                },
                "audio": {
                    "count": (
                        (1 if audio_vector is not None else 0)
                        + len(audio_segment_core_rows)
                    ),
                    "dims": 512,
                },
                "text": {
                    "count": len(transcript_core_rows) + len(ocr_chunk_core_rows),
                    "dims": 768,
                },
            },
            "evidence": {
                "frames": len(image_core_rows),
                "snippets": len(ocr_chunk_core_rows),
                "segments": len(transcript_core_rows) + len(audio_segment_core_rows),
            },
        }

        return PipelineResult(
            counts={
                "MediaAsset": 1,
                "ImageAsset": len(image_core_rows),
                "DocChunk": len(ocr_chunk_core_rows),
                "Transcript": len(transcript_core_rows),
                "AudioClip": 1 if audio_clip_core else 0,
                "AudioSegment": len(audio_segment_core_rows),
                "DerivedFrom": len(derived_edges),
                "NextKeyframe": len(next_keyframe_edges),
                "NextTranscript": len(next_transcript_edges),
            },
            manifest_uri=manifest_path,
            media_asset_id=media_asset_id,
            duration_ms=duration_ms,
            metrics=metrics,
        )
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)
        if audio_path:
            cleanup_tmp(audio_path)
