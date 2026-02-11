import os
from dataclasses import dataclass
from functools import lru_cache

from retikon_core.capabilities import get_edition, resolve_capabilities
from retikon_core.storage.paths import (
    backend_scheme,
    graph_root,
    has_uri_scheme,
    join_uri,
    normalize_bucket_uri,
)


@dataclass(frozen=True)
class Config:
    raw_bucket: str
    graph_bucket: str
    graph_prefix: str
    raw_prefix: str
    storage_backend: str
    local_graph_root: str | None
    env: str
    log_level: str
    max_raw_bytes: int
    max_video_seconds: int
    max_audio_seconds: int
    max_frames_per_video: int
    chunk_target_tokens: int
    chunk_overlap_tokens: int
    video_scene_threshold: float
    video_scene_min_frames: int
    video_thumbnail_width: int
    video_segment_preview_seconds: int
    audio_transcribe: bool
    audio_profile: bool
    audio_skip_normalize_if_wav: bool
    audio_max_segments: int
    audio_vad_enabled: bool
    audio_vad_frame_ms: int
    audio_vad_silence_db: float
    audio_vad_min_speech_ms: int
    transcribe_tier: str
    transcribe_max_ms: int
    firestore_collection: str
    idempotency_ttl_seconds: int
    idempotency_completed_ttl_seconds: int
    max_ingest_attempts: int
    allowed_doc_ext: tuple[str, ...]
    allowed_image_ext: tuple[str, ...]
    allowed_audio_ext: tuple[str, ...]
    allowed_video_ext: tuple[str, ...]
    ingestion_dry_run: bool
    video_sample_fps: float
    video_sample_interval_seconds: float
    rate_limit_doc_per_min: int
    rate_limit_image_per_min: int
    rate_limit_audio_per_min: int
    rate_limit_video_per_min: int
    rate_limit_global_doc_per_min: int
    rate_limit_global_image_per_min: int
    rate_limit_global_audio_per_min: int
    rate_limit_global_video_per_min: int
    rate_limit_backend: str
    redis_host: str | None
    redis_port: int
    redis_db: int
    redis_ssl: bool
    redis_password: str | None
    dlq_topic: str | None
    enable_ocr: bool
    ocr_max_pages: int
    default_org_id: str | None
    default_site_id: str | None
    default_stream_id: str | None
    edition: str
    capabilities: tuple[str, ...]
    snapshot_uri: str | None = None

    def graph_root_uri(self) -> str:
        if self.storage_backend == "local":
            if not self.local_graph_root:
                raise ValueError("LOCAL_GRAPH_ROOT is required for local storage")
            return self.local_graph_root
        return graph_root(self.bucket_uri(self.graph_bucket), self.graph_prefix)

    def storage_scheme(self) -> str | None:
        return backend_scheme(self.storage_backend)

    def bucket_uri(self, bucket: str) -> str:
        scheme = self.storage_scheme()
        if self.storage_backend != "local" and scheme is None and not has_uri_scheme(
            bucket
        ):
            raise ValueError(
                "Bucket must include a URI scheme when STORAGE_BACKEND="
                f"{self.storage_backend} (example: s3://bucket)"
            )
        return normalize_bucket_uri(bucket, scheme=scheme)

    def raw_object_uri(self, name: str, bucket: str | None = None) -> str:
        if self.storage_backend == "local":
            raise ValueError("raw_object_uri is not available for local storage")
        base = self.bucket_uri(bucket or self.raw_bucket)
        return join_uri(base, name)

    @classmethod
    def from_env(cls) -> "Config":
        missing: list[str] = []

        def require(name: str) -> str:
            value = os.getenv(name)
            if value is None or value == "":
                missing.append(name)
                return ""
            return value

        def require_int(name: str) -> int:
            value = require(name)
            if not value:
                return 0
            try:
                return int(value)
            except ValueError as exc:
                raise ValueError(f"{name} must be an integer") from exc

        storage_backend = os.getenv("STORAGE_BACKEND", "local").strip().lower()
        allowed_backends = {"local", "gcs", "gs", "s3", "remote", "azure"}
        if storage_backend not in allowed_backends:
            allowed = ", ".join(sorted(allowed_backends))
            raise ValueError(f"STORAGE_BACKEND must be one of: {allowed}")

        remote_required = storage_backend != "local"
        raw_bucket = require("RAW_BUCKET") if remote_required else os.getenv(
            "RAW_BUCKET", ""
        )
        graph_bucket = require("GRAPH_BUCKET") if remote_required else os.getenv(
            "GRAPH_BUCKET", ""
        )
        graph_prefix = require("GRAPH_PREFIX") if remote_required else os.getenv(
            "GRAPH_PREFIX", ""
        )
        raw_prefix = os.getenv("RAW_PREFIX", "raw").strip("/")
        local_graph_root = os.getenv("LOCAL_GRAPH_ROOT")
        if storage_backend == "local" and not local_graph_root:
            missing.append("LOCAL_GRAPH_ROOT")
        env = require("ENV")
        log_level = require("LOG_LEVEL")
        max_raw_bytes = require_int("MAX_RAW_BYTES")
        max_video_seconds = require_int("MAX_VIDEO_SECONDS")
        max_audio_seconds = require_int("MAX_AUDIO_SECONDS")
        max_frames_per_video = require_int("MAX_FRAMES_PER_VIDEO")
        chunk_target_tokens = require_int("CHUNK_TARGET_TOKENS")
        chunk_overlap_tokens = require_int("CHUNK_OVERLAP_TOKENS")
        video_scene_threshold = _parse_float(os.getenv("VIDEO_SCENE_THRESHOLD", "0.3"))
        video_scene_min_frames = int(os.getenv("VIDEO_SCENE_MIN_FRAMES", "3"))
        video_thumbnail_width = int(os.getenv("VIDEO_THUMBNAIL_WIDTH", "320"))
        video_segment_preview_seconds = int(
            os.getenv("VIDEO_SEGMENT_PREVIEW_SECONDS", "5")
        )
        audio_transcribe = _parse_bool(os.getenv("AUDIO_TRANSCRIBE"), True)
        audio_profile = _parse_bool(os.getenv("AUDIO_PROFILE"), False)
        audio_skip_normalize_if_wav = _parse_bool(
            os.getenv("AUDIO_SKIP_NORMALIZE_IF_WAV"),
            False,
        )
        audio_max_segments = int(os.getenv("AUDIO_MAX_SEGMENTS", "0"))
        audio_vad_enabled = _parse_bool(os.getenv("AUDIO_VAD_ENABLED"), True)
        audio_vad_frame_ms = int(os.getenv("AUDIO_VAD_FRAME_MS", "30"))
        audio_vad_silence_db = float(os.getenv("AUDIO_VAD_SILENCE_DB", "-45.0"))
        audio_vad_min_speech_ms = int(os.getenv("AUDIO_VAD_MIN_SPEECH_MS", "300"))
        transcribe_enabled = _parse_bool(
            os.getenv("TRANSCRIBE_ENABLED"),
            True,
        )
        transcribe_tier = os.getenv("TRANSCRIBE_TIER", "accurate").strip().lower()
        if not transcribe_enabled:
            audio_transcribe = False
            transcribe_tier = "off"
        elif transcribe_tier not in {"fast", "accurate", "off"}:
            raise ValueError(
                "TRANSCRIBE_TIER must be one of: fast, accurate, off"
            )
        transcribe_max_ms = int(os.getenv("TRANSCRIBE_MAX_MS", "0"))
        firestore_collection = os.getenv("FIRESTORE_COLLECTION", "ingestion_events")
        idempotency_ttl_seconds = int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "600"))
        idempotency_completed_ttl_seconds = int(
            os.getenv("IDEMPOTENCY_COMPLETED_TTL_SECONDS", "0")
        )
        max_ingest_attempts = int(os.getenv("MAX_INGEST_ATTEMPTS", "5"))
        allowed_doc_ext = _parse_ext_list(
            os.getenv(
                "ALLOWED_DOC_EXT",
                ".pdf,.txt,.md,.rtf,.docx,.pptx,.csv,.tsv,.xlsx,.xls",
            )
        )
        allowed_image_ext = _parse_ext_list(
            os.getenv(
                "ALLOWED_IMAGE_EXT",
                ".jpg,.jpeg,.png,.webp,.bmp,.tiff,.gif",
            )
        )
        allowed_audio_ext = _parse_ext_list(
            os.getenv(
                "ALLOWED_AUDIO_EXT",
                ".mp3,.wav,.flac,.m4a,.aac,.ogg,.opus",
            )
        )
        allowed_video_ext = _parse_ext_list(
            os.getenv(
                "ALLOWED_VIDEO_EXT",
                ".mp4,.mov,.mkv,.webm,.avi,.mpeg,.mpg",
            )
        )
        ingestion_dry_run = os.getenv("INGESTION_DRY_RUN", "0") == "1"
        video_sample_fps = _parse_float(os.getenv("VIDEO_SAMPLE_FPS", "1.0"))
        video_sample_interval_seconds = _parse_float(
            os.getenv("VIDEO_SAMPLE_INTERVAL_SECONDS", "0")
        )
        rate_limit_doc_per_min = int(os.getenv("RATE_LIMIT_DOC_PER_MIN", "60"))
        rate_limit_image_per_min = int(os.getenv("RATE_LIMIT_IMAGE_PER_MIN", "60"))
        rate_limit_audio_per_min = int(os.getenv("RATE_LIMIT_AUDIO_PER_MIN", "20"))
        rate_limit_video_per_min = int(os.getenv("RATE_LIMIT_VIDEO_PER_MIN", "10"))
        rate_limit_global_doc_per_min = int(
            os.getenv("RATE_LIMIT_GLOBAL_DOC_PER_MIN", "0")
        )
        rate_limit_global_image_per_min = int(
            os.getenv("RATE_LIMIT_GLOBAL_IMAGE_PER_MIN", "0")
        )
        rate_limit_global_audio_per_min = int(
            os.getenv("RATE_LIMIT_GLOBAL_AUDIO_PER_MIN", "0")
        )
        rate_limit_global_video_per_min = int(
            os.getenv("RATE_LIMIT_GLOBAL_VIDEO_PER_MIN", "0")
        )
        rate_limit_backend = os.getenv("RATE_LIMIT_BACKEND", "local").strip().lower()
        if rate_limit_backend not in {"none", "local", "redis"}:
            raise ValueError(
                "RATE_LIMIT_BACKEND must be one of: none, local, redis"
            )
        redis_host = os.getenv("REDIS_HOST")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        redis_db = int(os.getenv("REDIS_DB", "0"))
        redis_ssl = os.getenv("REDIS_SSL", "0") == "1"
        redis_password = os.getenv("REDIS_PASSWORD")
        dlq_topic = os.getenv("DLQ_TOPIC")
        enable_ocr = os.getenv("ENABLE_OCR", "0") == "1"
        ocr_max_pages = int(os.getenv("OCR_MAX_PAGES", "5"))
        default_org_id = os.getenv("DEFAULT_ORG_ID")
        default_site_id = os.getenv("DEFAULT_SITE_ID")
        default_stream_id = os.getenv("DEFAULT_STREAM_ID")
        snapshot_uri = os.getenv("SNAPSHOT_URI")
        edition = get_edition(os.getenv("RETIKON_EDITION"))
        capabilities = resolve_capabilities(
            edition=edition,
            override=os.getenv("RETIKON_CAPABILITIES"),
        )

        if remote_required and backend_scheme(storage_backend) is None:
            if raw_bucket and not has_uri_scheme(raw_bucket):
                raise ValueError(
                    "RAW_BUCKET must include a URI scheme when STORAGE_BACKEND="
                    f"{storage_backend} (example: s3://bucket)"
                )
            if graph_bucket and not has_uri_scheme(graph_bucket):
                raise ValueError(
                    "GRAPH_BUCKET must include a URI scheme when STORAGE_BACKEND="
                    f"{storage_backend} (example: s3://bucket)"
                )

        if missing:
            missing_str = ", ".join(missing)
            raise ValueError(f"Missing required env vars: {missing_str}")

        return cls(
            raw_bucket=raw_bucket,
            graph_bucket=graph_bucket,
            graph_prefix=graph_prefix,
            raw_prefix=raw_prefix,
            storage_backend=storage_backend,
            local_graph_root=local_graph_root,
            env=env,
            log_level=log_level,
            max_raw_bytes=max_raw_bytes,
            max_video_seconds=max_video_seconds,
            max_audio_seconds=max_audio_seconds,
            max_frames_per_video=max_frames_per_video,
            chunk_target_tokens=chunk_target_tokens,
            chunk_overlap_tokens=chunk_overlap_tokens,
            video_scene_threshold=video_scene_threshold,
            video_scene_min_frames=video_scene_min_frames,
            video_thumbnail_width=video_thumbnail_width,
            video_segment_preview_seconds=video_segment_preview_seconds,
            audio_transcribe=audio_transcribe,
            audio_profile=audio_profile,
            audio_skip_normalize_if_wav=audio_skip_normalize_if_wav,
            audio_max_segments=audio_max_segments,
            audio_vad_enabled=audio_vad_enabled,
            audio_vad_frame_ms=audio_vad_frame_ms,
            audio_vad_silence_db=audio_vad_silence_db,
            audio_vad_min_speech_ms=audio_vad_min_speech_ms,
            transcribe_tier=transcribe_tier,
            transcribe_max_ms=transcribe_max_ms,
            firestore_collection=firestore_collection,
            idempotency_ttl_seconds=idempotency_ttl_seconds,
            idempotency_completed_ttl_seconds=idempotency_completed_ttl_seconds,
            max_ingest_attempts=max_ingest_attempts,
            allowed_doc_ext=allowed_doc_ext,
            allowed_image_ext=allowed_image_ext,
            allowed_audio_ext=allowed_audio_ext,
            allowed_video_ext=allowed_video_ext,
            ingestion_dry_run=ingestion_dry_run,
            video_sample_fps=video_sample_fps,
            video_sample_interval_seconds=video_sample_interval_seconds,
            rate_limit_doc_per_min=rate_limit_doc_per_min,
            rate_limit_image_per_min=rate_limit_image_per_min,
            rate_limit_audio_per_min=rate_limit_audio_per_min,
            rate_limit_video_per_min=rate_limit_video_per_min,
            rate_limit_global_doc_per_min=rate_limit_global_doc_per_min,
            rate_limit_global_image_per_min=rate_limit_global_image_per_min,
            rate_limit_global_audio_per_min=rate_limit_global_audio_per_min,
            rate_limit_global_video_per_min=rate_limit_global_video_per_min,
            rate_limit_backend=rate_limit_backend,
            redis_host=redis_host,
            redis_port=redis_port,
            redis_db=redis_db,
            redis_ssl=redis_ssl,
            redis_password=redis_password,
            dlq_topic=dlq_topic,
            enable_ocr=enable_ocr,
            ocr_max_pages=ocr_max_pages,
            default_org_id=default_org_id,
            default_site_id=default_site_id,
            default_stream_id=default_stream_id,
            edition=edition,
            capabilities=capabilities,
            snapshot_uri=snapshot_uri,
        )


def _parse_ext_list(value: str) -> tuple[str, ...]:
    items = []
    for raw in value.split(","):
        cleaned = raw.strip().lower()
        if not cleaned:
            continue
        if not cleaned.startswith("."):
            cleaned = f".{cleaned}"
        items.append(cleaned)
    return tuple(items)


def _parse_float(value: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"Invalid float value: {value}") from exc


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config.from_env()
