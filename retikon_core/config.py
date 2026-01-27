import os
from dataclasses import dataclass
from functools import lru_cache

from retikon_core.capabilities import get_edition, resolve_capabilities
from retikon_core.storage.paths import graph_root


@dataclass(frozen=True)
class Config:
    raw_bucket: str
    graph_bucket: str
    graph_prefix: str
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
    firestore_collection: str
    idempotency_ttl_seconds: int
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
    dlq_topic: str | None
    enable_ocr: bool
    ocr_max_pages: int
    edition: str
    capabilities: tuple[str, ...]
    snapshot_uri: str | None = None

    def graph_root_uri(self) -> str:
        if self.storage_backend == "local":
            if not self.local_graph_root:
                raise ValueError("LOCAL_GRAPH_ROOT is required for local storage")
            return self.local_graph_root
        return graph_root(self.graph_bucket, self.graph_prefix)

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

        storage_backend = os.getenv("STORAGE_BACKEND", "gcs").strip().lower()
        if storage_backend not in {"gcs", "local"}:
            raise ValueError("STORAGE_BACKEND must be 'gcs' or 'local'")

        raw_bucket = require("RAW_BUCKET") if storage_backend == "gcs" else os.getenv(
            "RAW_BUCKET", ""
        )
        graph_bucket = (
            require("GRAPH_BUCKET")
            if storage_backend == "gcs"
            else os.getenv("GRAPH_BUCKET", "")
        )
        graph_prefix = (
            require("GRAPH_PREFIX")
            if storage_backend == "gcs"
            else os.getenv("GRAPH_PREFIX", "")
        )
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
        firestore_collection = os.getenv("FIRESTORE_COLLECTION", "ingestion_events")
        idempotency_ttl_seconds = int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "600"))
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
        dlq_topic = os.getenv("DLQ_TOPIC")
        enable_ocr = os.getenv("ENABLE_OCR", "0") == "1"
        ocr_max_pages = int(os.getenv("OCR_MAX_PAGES", "5"))
        snapshot_uri = os.getenv("SNAPSHOT_URI")
        edition = get_edition(os.getenv("RETIKON_EDITION"))
        capabilities = resolve_capabilities(
            edition=edition,
            override=os.getenv("RETIKON_CAPABILITIES"),
        )

        if missing:
            missing_str = ", ".join(missing)
            raise ValueError(f"Missing required env vars: {missing_str}")

        return cls(
            raw_bucket=raw_bucket,
            graph_bucket=graph_bucket,
            graph_prefix=graph_prefix,
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
            firestore_collection=firestore_collection,
            idempotency_ttl_seconds=idempotency_ttl_seconds,
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
            dlq_topic=dlq_topic,
            enable_ocr=enable_ocr,
            ocr_max_pages=ocr_max_pages,
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


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config.from_env()
