from __future__ import annotations

import os
import time
from dataclasses import dataclass

from retikon_core.config import Config
from retikon_core.errors import RecoverableError
from retikon_core.tenancy.types import TenantScope

try:
    import redis
except ImportError:  # pragma: no cover - optional dependency for redis backend
    redis = None


@dataclass
class TokenBucket:
    capacity: float
    refill_per_sec: float
    tokens: float
    last_refill: float

    def allow(self, cost: float = 1.0) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        if elapsed > 0:
            self.tokens = min(
                self.capacity,
                self.tokens + elapsed * self.refill_per_sec,
            )
            self.last_refill = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False


class RateLimitExceeded(RecoverableError):
    pass


class RateLimitBackendError(RecoverableError):
    pass


_LOCAL_BUCKETS: dict[str, TokenBucket] = {}
_REDIS_CLIENT = None
_REDIS_KEY: tuple[object, ...] | None = None


def reset_rate_limit_state() -> None:
    _LOCAL_BUCKETS.clear()
    global _REDIS_CLIENT, _REDIS_KEY
    _REDIS_CLIENT = None
    _REDIS_KEY = None


def _rate_for_modality(config: Config | None, modality: str) -> int:
    if config is None:
        return _rate_for_modality_env(modality)
    if modality == "document":
        return config.rate_limit_doc_per_min
    if modality == "image":
        return config.rate_limit_image_per_min
    if modality == "audio":
        return config.rate_limit_audio_per_min
    if modality == "video":
        return config.rate_limit_video_per_min
    return 0


def _rate_for_modality_env(modality: str) -> int:
    if modality == "document":
        return int(os.getenv("RATE_LIMIT_DOC_PER_MIN", "60"))
    if modality == "image":
        return int(os.getenv("RATE_LIMIT_IMAGE_PER_MIN", "60"))
    if modality == "audio":
        return int(os.getenv("RATE_LIMIT_AUDIO_PER_MIN", "20"))
    if modality == "video":
        return int(os.getenv("RATE_LIMIT_VIDEO_PER_MIN", "10"))
    return 0


def _rate_limit_backend(config: Config | None) -> str:
    if config is not None:
        value = getattr(config, "rate_limit_backend", "local")
    else:
        value = os.getenv("RATE_LIMIT_BACKEND", "local")
    backend = str(value).strip().lower()
    if backend not in {"none", "local", "redis"}:
        raise RateLimitBackendError(f"Unsupported rate limit backend: {backend}")
    return backend


def _scope_key(scope: TenantScope | None, config: Config | None) -> str:
    if scope is None and config is not None:
        scope = TenantScope(
            org_id=config.default_org_id,
            site_id=config.default_site_id,
            stream_id=config.default_stream_id,
        )
    org_id = scope.org_id if scope and scope.org_id else "none"
    site_id = scope.site_id if scope and scope.site_id else "none"
    stream_id = scope.stream_id if scope and scope.stream_id else "none"
    return f"{org_id}:{site_id}:{stream_id}"


def _redis_settings(config: Config | None) -> tuple[str | None, int, int, bool, str | None]:
    if config is not None:
        host = getattr(config, "redis_host", None)
        port = getattr(config, "redis_port", 6379)
        db = getattr(config, "redis_db", 0)
        ssl = getattr(config, "redis_ssl", False)
        password = getattr(config, "redis_password", None)
        return host, int(port), int(db), bool(ssl), password
    host = os.getenv("REDIS_HOST")
    port = int(os.getenv("REDIS_PORT", "6379"))
    db = int(os.getenv("REDIS_DB", "0"))
    ssl = os.getenv("REDIS_SSL", "0") == "1"
    password = os.getenv("REDIS_PASSWORD")
    return host, port, db, ssl, password


def _redis_client(config: Config | None):
    global _REDIS_CLIENT, _REDIS_KEY
    if redis is None:
        raise RateLimitBackendError("Redis backend requires the redis package")
    host, port, db, ssl, password = _redis_settings(config)
    if not host:
        raise RateLimitBackendError("REDIS_HOST is required for redis rate limiting")
    key = (host, port, db, ssl, password)
    if _REDIS_CLIENT is not None and _REDIS_KEY == key:
        return _REDIS_CLIENT
    _REDIS_CLIENT = redis.Redis(
        host=host,
        port=port,
        db=db,
        ssl=ssl,
        password=password,
    )
    _REDIS_KEY = key
    return _REDIS_CLIENT


def _redis_allow(*, key: str, limit: int, cost: int, config: Config | None) -> bool:
    client = _redis_client(config)
    try:
        pipe = client.pipeline()
        pipe.incrby(key, cost)
        pipe.expire(key, 60, nx=True)
        count, _ = pipe.execute()
    except Exception as exc:
        raise RateLimitBackendError("Redis rate limiter unavailable") from exc
    return int(count) <= limit


def enforce_rate_limit(
    modality: str,
    config: Config | None = None,
    scope: TenantScope | None = None,
    cost: int = 1,
) -> None:
    rate_per_min = _rate_for_modality(config, modality)
    if rate_per_min <= 0:
        return
    backend = _rate_limit_backend(config)
    if backend == "none":
        return
    scope_key = _scope_key(scope, config)
    if backend == "local":
        key = f"{scope_key}:{modality}"
        bucket = _LOCAL_BUCKETS.get(key)
        if bucket is None:
            bucket = TokenBucket(
                capacity=float(rate_per_min),
                refill_per_sec=float(rate_per_min) / 60.0,
                tokens=float(rate_per_min),
                last_refill=time.monotonic(),
            )
            _LOCAL_BUCKETS[key] = bucket
        if not bucket.allow(cost=cost):
            raise RateLimitExceeded(f"Rate limit exceeded for {modality}")
        return
    if backend == "redis":
        window = int(time.time() // 60)
        key = f"ratelimit:{scope_key}:{modality}:{window}"
        if not _redis_allow(key=key, limit=rate_per_min, cost=cost, config=config):
            raise RateLimitExceeded(f"Rate limit exceeded for {modality}")
        return
