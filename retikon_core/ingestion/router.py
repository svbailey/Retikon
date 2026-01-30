from __future__ import annotations

import os
from dataclasses import dataclass

from retikon_core.config import Config
from retikon_core.errors import PermanentError
from retikon_core.ingestion.download import DownloadResult, cleanup_tmp, download_to_tmp
from retikon_core.ingestion.pipelines import audio, document, image, video
from retikon_core.ingestion.rate_limit import enforce_rate_limit
from retikon_core.ingestion.storage_event import StorageEvent
from retikon_core.ingestion.types import IngestSource
from retikon_core.storage.paths import has_uri_scheme, join_uri
from retikon_core.tenancy import scope_from_metadata
from retikon_core.tenancy.types import TenantScope


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


def _ensure_allowed(event: StorageEvent, config: Config, modality: str) -> None:
    extension = _extension_for_event(event)
    if modality == "document" and extension not in config.allowed_doc_ext:
        raise PermanentError(f"Unsupported document extension: {extension}")
    if modality == "image" and extension not in config.allowed_image_ext:
        raise PermanentError(f"Unsupported image extension: {extension}")
    if modality == "audio" and extension not in config.allowed_audio_ext:
        raise PermanentError(f"Unsupported audio extension: {extension}")
    if modality == "video" and extension not in config.allowed_video_ext:
        raise PermanentError(f"Unsupported video extension: {extension}")
    if event.content_type:
        normalized = _normalize_content_type(event.content_type)
        allowed_types = _CONTENT_TYPE_BY_EXT.get(extension, set())
        if not normalized or normalized not in allowed_types:
            raise PermanentError(
                f"Content type does not match extension: {event.content_type}"
            )


_CONTENT_TYPE_EXT: dict[str, str] = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "application/rtf": ".rtf",
    "text/rtf": ".rtf",
    (
        "application/vnd.openxmlformats-officedocument."
        "wordprocessingml.document"
    ): ".docx",
    (
        "application/vnd.openxmlformats-officedocument."
        "presentationml.presentation"
    ): ".pptx",
    "text/csv": ".csv",
    "application/csv": ".csv",
    "text/tab-separated-values": ".tsv",
    "text/tsv": ".tsv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
    "image/gif": ".gif",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/x-msvideo": ".avi",
    "video/webm": ".webm",
    "video/x-matroska": ".mkv",
    "video/mpeg": ".mpeg",
}

_CONTENT_TYPE_BY_EXT: dict[str, set[str]] = {}
for _ctype, _ext in _CONTENT_TYPE_EXT.items():
    _CONTENT_TYPE_BY_EXT.setdefault(_ext, set()).add(_ctype)
_CONTENT_TYPE_BY_EXT.setdefault(".jpeg", set()).add("image/jpeg")
_CONTENT_TYPE_BY_EXT.setdefault(".mpg", set()).add("video/mpeg")


def _normalize_content_type(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(";", 1)[0].strip().lower()


def _extension_for_event(event: StorageEvent) -> str:
    if event.extension:
        return event.extension
    if event.content_type:
        normalized = _normalize_content_type(event.content_type)
        if normalized:
            return _CONTENT_TYPE_EXT.get(normalized, "")
    return ""


def _check_size(event: StorageEvent, config: Config) -> None:
    if event.size is not None and event.size > config.max_raw_bytes:
        raise PermanentError(f"Object too large: {event.size} bytes")


def _make_source(
    event: StorageEvent,
    download: DownloadResult,
    config: Config,
) -> IngestSource:
    default_scope = TenantScope(
        org_id=config.default_org_id,
        site_id=config.default_site_id,
        stream_id=config.default_stream_id,
    )
    scope = scope_from_metadata(download.metadata, defaults=default_scope)
    uri_scheme = None
    if not has_uri_scheme(event.bucket):
        uri_scheme = config.storage_scheme()
        if config.storage_backend != "local" and uri_scheme is None:
            raise PermanentError(
                "Bucket must include a URI scheme when STORAGE_BACKEND="
                f"{config.storage_backend} (example: s3://bucket)"
            )

    return IngestSource(
        bucket=event.bucket,
        name=event.name,
        generation=event.generation,
        content_type=download.content_type or event.content_type,
        size_bytes=download.size_bytes or event.size,
        md5_hash=download.md5_hash or event.md5_hash,
        crc32c=download.crc32c or event.crc32c,
        local_path=download.path,
        org_id=scope.org_id,
        site_id=scope.site_id,
        stream_id=scope.stream_id,
        metadata=download.metadata,
        uri_scheme=uri_scheme,
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
    event: StorageEvent,
    config: Config,
) -> PipelineOutcome:
    _check_size(event, config)
    modality = _modality_for_name(event.name)
    _ensure_allowed(event, config, modality)
    enforce_rate_limit(modality, config)

    output_uri = config.graph_root_uri()
    pipeline_version_value = pipeline_version()
    schema_version = _schema_version()

    try:
        if config.storage_backend == "local":
            object_uri = join_uri(event.bucket, event.name)
        else:
            object_uri = config.raw_object_uri(event.name, bucket=event.bucket)
    except ValueError as exc:
        raise PermanentError(str(exc)) from exc
    download = download_to_tmp(object_uri, config.max_raw_bytes)
    try:
        source = _make_source(event, download, config)
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
