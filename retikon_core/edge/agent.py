from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from retikon_core.config import get_config
from retikon_core.logging import configure_logging, get_logger

SERVICE_NAME = "retikon-edge-agent"

configure_logging(
    service=SERVICE_NAME,
    env=os.getenv("ENV", "local"),
    version=os.getenv("RETIKON_VERSION"),
)
logger = get_logger(__name__)


def guess_content_type(path: Path) -> str | None:
    return mimetypes.guess_type(path.as_posix())[0]


def _post_json(
    url: str,
    payload: dict[str, Any],
    timeout: int = 30,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def ingest_path(
    path: Path,
    ingest_url: str,
    *,
    timeout: int = 30,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"path": path.as_posix()}
    content_type = guess_content_type(path)
    if content_type:
        payload["content_type"] = content_type
    response = _post_json(ingest_url, payload, timeout=timeout)
    return response


def _iter_files(root: Path, recursive: bool) -> Iterable[Path]:
    if recursive:
        yield from (item for item in root.rglob("*") if item.is_file())
        return
    yield from (item for item in root.iterdir() if item.is_file())


def _allowed_exts_from_env() -> tuple[str, ...]:
    raw = os.getenv("EDGE_ALLOWED_EXT")
    if raw:
        items = [item.strip().lower() for item in raw.split(",") if item.strip()]
        return tuple(sorted(set(items)))
    try:
        config = get_config()
    except Exception:
        return ()
    allowed = (
        list(config.allowed_doc_ext)
        + list(config.allowed_image_ext)
        + list(config.allowed_audio_ext)
        + list(config.allowed_video_ext)
    )
    return tuple(sorted(set(allowed)))


def scan_and_ingest(
    root: Path,
    ingest_url: str,
    *,
    recursive: bool = True,
    max_files: int | None = None,
    allowed_exts: tuple[str, ...] | None = None,
    timeout: int = 30,
) -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = []
    if not root.exists():
        raise FileNotFoundError(f"Watch path not found: {root}")
    if allowed_exts is None:
        allowed_exts = _allowed_exts_from_env()
    count = 0
    for path in sorted(_iter_files(root, recursive)):
        if allowed_exts and path.suffix.lower() not in allowed_exts:
            continue
        responses.append(ingest_path(path, ingest_url, timeout=timeout))
        count += 1
        if max_files and count >= max_files:
            break
    return responses


def run_agent() -> None:
    watch_path = Path(os.getenv("EDGE_WATCH_PATH", "."))
    ingest_url = os.getenv("EDGE_INGEST_URL", "http://localhost:8081/ingest")
    recursive = os.getenv("EDGE_RECURSIVE", "1") == "1"
    poll_interval = float(os.getenv("EDGE_POLL_INTERVAL", "5"))
    max_files = os.getenv("EDGE_MAX_FILES_PER_BATCH")
    timeout = int(os.getenv("EDGE_REQUEST_TIMEOUT", "30"))
    run_once = os.getenv("EDGE_RUN_ONCE", "0") == "1"

    max_files_value = int(max_files) if max_files else None

    logger.info(
        "Edge agent started",
        extra={
            "watch_path": str(watch_path),
            "ingest_url": ingest_url,
            "recursive": recursive,
            "poll_interval_s": poll_interval,
            "max_files": max_files_value,
            "run_once": run_once,
        },
    )

    while True:
        try:
            responses = scan_and_ingest(
                watch_path,
                ingest_url,
                recursive=recursive,
                max_files=max_files_value,
                timeout=timeout,
            )
            if responses:
                logger.info(
                    "Edge batch uploaded",
                    extra={"count": len(responses)},
                )
        except Exception as exc:
            logger.warning(
                "Edge agent scan failed",
                extra={"error_message": str(exc)},
            )

        if run_once:
            break
        time.sleep(max(0.1, poll_interval))


if __name__ == "__main__":
    run_agent()
