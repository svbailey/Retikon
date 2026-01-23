import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Config:
    raw_bucket: str
    graph_bucket: str
    graph_prefix: str
    env: str
    log_level: str
    max_raw_bytes: int
    max_video_seconds: int
    max_audio_seconds: int
    chunk_target_tokens: int
    chunk_overlap_tokens: int
    snapshot_uri: str | None = None

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

        raw_bucket = require("RAW_BUCKET")
        graph_bucket = require("GRAPH_BUCKET")
        graph_prefix = require("GRAPH_PREFIX")
        env = require("ENV")
        log_level = require("LOG_LEVEL")
        max_raw_bytes = require_int("MAX_RAW_BYTES")
        max_video_seconds = require_int("MAX_VIDEO_SECONDS")
        max_audio_seconds = require_int("MAX_AUDIO_SECONDS")
        chunk_target_tokens = require_int("CHUNK_TARGET_TOKENS")
        chunk_overlap_tokens = require_int("CHUNK_OVERLAP_TOKENS")
        snapshot_uri = os.getenv("SNAPSHOT_URI")

        if missing:
            missing_str = ", ".join(missing)
            raise ValueError(f"Missing required env vars: {missing_str}")

        return cls(
            raw_bucket=raw_bucket,
            graph_bucket=graph_bucket,
            graph_prefix=graph_prefix,
            env=env,
            log_level=log_level,
            max_raw_bytes=max_raw_bytes,
            max_video_seconds=max_video_seconds,
            max_audio_seconds=max_audio_seconds,
            chunk_target_tokens=chunk_target_tokens,
            chunk_overlap_tokens=chunk_overlap_tokens,
            snapshot_uri=snapshot_uri,
        )


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config.from_env()
