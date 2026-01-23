import json
import logging
import os
import time
from typing import Any


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
            "version",
        ):
            value = getattr(record, key, None)
            if value is not None:
                base[key] = value

        if record.exc_info:
            base["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(base, ensure_ascii=True)


class BaseFieldFilter(logging.Filter):
    def __init__(self, service: str, env: str | None, version: str | None) -> None:
        super().__init__()
        self.service = service
        self.env = env
        self.version = version

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "service", None) is None:
            record.service = self.service
        if getattr(record, "env", None) is None:
            record.env = self.env
        if getattr(record, "version", None) is None:
            record.version = self.version
        return True


def configure_logging(
    service: str,
    env: str | None = None,
    version: str | None = None,
) -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    root = logging.getLogger()
    root.setLevel(log_level)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(BaseFieldFilter(service=service, env=env, version=version))

    if root.handlers:
        root.handlers = []
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
