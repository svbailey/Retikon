import json
import logging
import os
import time
from typing import Any, Sequence

from retikon_core.capabilities import get_edition, resolve_capabilities


def _utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base: dict[str, Any] = {
            "timestamp": _utc_timestamp(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key in (
            "service",
            "env",
            "request_id",
            "correlation_id",
            "duration_ms",
            "processing_ms",
            "version",
            "edition",
            "capabilities",
            "modality",
            "bytes_downloaded",
            "media_asset_id",
            "attempt_count",
            "status",
            "error_code",
            "error_message",
            "top_k",
            "snapshot_path",
            "snapshot_loaded_at",
            "snapshot_age_s",
            "snapshot_load_ms",
            "snapshot_size_bytes",
            "snapshot_metadata",
            "healthcheck_ms",
            "timings",
            "control_plane_op",
            "control_plane_primary",
            "control_plane_secondary",
            "control_plane_reason",
            "control_plane_primary_empty",
            "control_plane_secondary_empty",
            "control_plane_primary_size",
            "control_plane_secondary_size",
            "control_plane_mismatch",
        ):
            value = getattr(record, key, None)
            if value is not None:
                base[key] = value

        if record.exc_info:
            base["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(base, ensure_ascii=True)


class BaseFieldFilter(logging.Filter):
    def __init__(
        self,
        service: str,
        env: str | None,
        version: str | None,
        edition: str,
        capabilities: Sequence[str],
    ) -> None:
        super().__init__()
        self.service = service
        self.env = env
        self.version = version
        self.edition = edition
        self.capabilities = list(capabilities)

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "service", None) is None:
            record.service = self.service
        if getattr(record, "env", None) is None:
            record.env = self.env
        if getattr(record, "version", None) is None:
            record.version = self.version
        if getattr(record, "edition", None) is None:
            record.edition = self.edition
        if getattr(record, "capabilities", None) is None:
            record.capabilities = self.capabilities
        return True


def configure_logging(
    service: str,
    env: str | None = None,
    version: str | None = None,
    edition: str | None = None,
    capabilities: Sequence[str] | None = None,
) -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    root = logging.getLogger()
    root.setLevel(log_level)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    resolved_edition = get_edition(edition)
    if capabilities is None:
        resolved_caps = resolve_capabilities(edition=resolved_edition)
    else:
        resolved_caps = tuple(capabilities)
    handler.addFilter(
        BaseFieldFilter(
            service=service,
            env=env,
            version=version,
            edition=resolved_edition,
            capabilities=resolved_caps,
        )
    )

    if root.handlers:
        root.handlers = []
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
