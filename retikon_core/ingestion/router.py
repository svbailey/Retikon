from __future__ import annotations

import os
from dataclasses import dataclass

from google.cloud import storage

from retikon_core.config import Config
from retikon_core.errors import PermanentError
from retikon_core.ingestion.download import DownloadResult, cleanup_tmp, download_to_tmp
from retikon_core.ingestion.eventarc import GcsEvent
from retikon_core.ingestion.pipelines import audio, document, image, video
from retikon_core.ingestion.rate_limit import enforce_rate_limit
from retikon_core.ingestion.types import IngestSource
from retikon_core.storage.paths import graph_root


@dataclass(frozen=True)
class PipelineOutcome:
    status: str
    counts: dict[str, int]
    manifest_uri: str | None = None
    modality: str | None = None
    media_asset_id: str | None = None


def pipeline_version() -> str:
    return os.getenv("PIPELINE_VERSION") or os.getenv("RETIKON_VERSION") or "dev"


def _schema_version() -> str:
    return "1"


def _modality_for_name(name: str) -> str:
    if name.startswith("raw/docs/"):
        return "document"
    if name.startswith("raw/images/"):
        return "image"
    if name.startswith("raw/audio/"):
        return "audio"
    if name.startswith("raw/videos/"):
        return "video"
    raise PermanentError(f"Unsupported object prefix: {name}")


def _ensure_allowed(event: GcsEvent, config: Config, modality: str) -> None:
    extension = _extension_for_event(event)
    if modality == "document" and extension not in config.allowed_doc_ext:
        raise PermanentError(f"Unsupported document extension: {extension}")
    if modality == "image" and extension not in config.allowed_image_ext:
        raise PermanentError(f"Unsupported image extension: {extension}")
    if modality == "audio" and extension not in config.allowed_audio_ext:
        raise PermanentError(f"Unsupported audio extension: {extension}")
    if modality == "video" and extension not in config.allowed_video_ext:
        raise PermanentError(f"Unsupported video extension: {extension}")


_CONTENT_TYPE_EXT: dict[str, str] = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/x-msvideo": ".avi",
}


def _extension_for_event(event: GcsEvent) -> str:
    if event.extension:
        return event.extension
    if event.content_type:
        return _CONTENT_TYPE_EXT.get(event.content_type.lower(), "")
    return ""


def _check_size(event: GcsEvent, config: Config) -> None:
    if event.size is not None and event.size > config.max_raw_bytes:
        raise PermanentError(f"Object too large: {event.size} bytes")


def _make_source(
    event: GcsEvent,
    download: DownloadResult,
) -> IngestSource:
    return IngestSource(
        bucket=event.bucket,
        name=event.name,
        generation=event.generation,
        content_type=download.content_type or event.content_type,
        size_bytes=download.size_bytes or event.size,
        md5_hash=download.md5_hash or event.md5_hash,
        crc32c=download.crc32c or event.crc32c,
        local_path=download.path,
    )


def _run_pipeline(
    *,
    modality: str,
    source: IngestSource | None,
    config: Config,
    output_uri: str,
    pipeline_version_value: str,
    schema_version: str,
) -> PipelineOutcome:
    if modality == "document":
        if source is None:
            raise PermanentError("Missing source for document pipeline")
        result = document.ingest_document(
            source=source,
            config=config,
            output_uri=output_uri,
            pipeline_version=pipeline_version_value,
            schema_version=schema_version,
        )
        return PipelineOutcome(
            status="completed",
            counts=result.counts,
            manifest_uri=result.manifest_uri,
            modality=modality,
            media_asset_id=result.media_asset_id,
        )
    if modality == "image":
        if source is None:
            raise PermanentError("Missing source for image pipeline")
        result = image.ingest_image(
            source=source,
            config=config,
            output_uri=output_uri,
            pipeline_version=pipeline_version_value,
            schema_version=schema_version,
        )
        return PipelineOutcome(
            status="completed",
            counts=result.counts,
            manifest_uri=result.manifest_uri,
            modality=modality,
            media_asset_id=result.media_asset_id,
        )
    if modality == "audio":
        if source is None:
            raise PermanentError("Missing source for audio pipeline")
        result = audio.ingest_audio(
            source=source,
            config=config,
            output_uri=output_uri,
            pipeline_version=pipeline_version_value,
            schema_version=schema_version,
        )
        return PipelineOutcome(
            status="completed",
            counts=result.counts,
            manifest_uri=result.manifest_uri,
            modality=modality,
            media_asset_id=result.media_asset_id,
        )
    if modality == "video":
        if source is None:
            raise PermanentError("Missing source for video pipeline")
        result = video.ingest_video(
            source=source,
            config=config,
            output_uri=output_uri,
            pipeline_version=pipeline_version_value,
            schema_version=schema_version,
        )
        return PipelineOutcome(
            status="completed",
            counts=result.counts,
            manifest_uri=result.manifest_uri,
            modality=modality,
            media_asset_id=result.media_asset_id,
        )
    raise PermanentError(f"Unsupported modality: {modality}")


def process_event(
    *,
    event: GcsEvent,
    config: Config,
    storage_client: storage.Client,
) -> PipelineOutcome:
    _check_size(event, config)
    modality = _modality_for_name(event.name)
    _ensure_allowed(event, config, modality)
    enforce_rate_limit(modality, config)

    output_uri = graph_root(config.graph_bucket, config.graph_prefix)
    pipeline_version_value = pipeline_version()
    schema_version = _schema_version()

    download = download_to_tmp(
        storage_client,
        event.bucket,
        event.name,
        config.max_raw_bytes,
    )
    try:
        source = _make_source(event, download)
        outcome = _run_pipeline(
            modality=modality,
            source=source,
            config=config,
            output_uri=output_uri,
            pipeline_version_value=pipeline_version_value,
            schema_version=schema_version,
        )
        return outcome
    finally:
        cleanup_tmp(download.path)
