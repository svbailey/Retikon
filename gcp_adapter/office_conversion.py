from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fsspec

from gcp_adapter.queue_pubsub import PubSubPublisher
from retikon_core.errors import PermanentError, RecoverableError
from retikon_core.storage.paths import join_uri

_STUB_PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@dataclass(frozen=True)
class OfficeConversionJob:
    id: str
    filename: str
    content_base64: str
    status: str
    output_uri: str | None
    error: str | None
    created_at: str
    updated_at: str


def conversion_record_uri(base_uri: str, job_id: str) -> str:
    return join_uri(base_uri, "control", "office_conversions", f"{job_id}.json")


def conversion_output_uri(base_uri: str, job_id: str) -> str:
    return join_uri(base_uri, "control", "office_conversions", f"{job_id}.pdf")


def save_conversion_record(base_uri: str, job: OfficeConversionJob) -> str:
    uri = conversion_record_uri(base_uri, job.id)
    fs, path = fsspec.core.url_to_fs(uri)
    fs.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
    payload = asdict(job)
    with fs.open(path, "wb") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
    return uri


def write_conversion_output(base_uri: str, job_id: str, content: bytes) -> str:
    uri = conversion_output_uri(base_uri, job_id)
    fs, path = fsspec.core.url_to_fs(uri)
    fs.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
    with fs.open(path, "wb") as handle:
        handle.write(content)
    return uri


def load_conversion_record(base_uri: str, job_id: str) -> OfficeConversionJob | None:
    uri = conversion_record_uri(base_uri, job_id)
    fs, path = fsspec.core.url_to_fs(uri)
    if not fs.exists(path):
        return None
    with fs.open(path, "rb") as handle:
        payload = json.loads(handle.read().decode("utf-8"))
    return OfficeConversionJob(**payload)


def enqueue_conversion(
    *,
    topic: str,
    payload: dict[str, Any],
) -> str:
    publisher = PubSubPublisher()
    return publisher.publish_json(topic=topic, payload=payload)


def publish_conversion_dlq(
    *,
    topic: str,
    payload: dict[str, Any],
) -> str:
    publisher = PubSubPublisher()
    return publisher.publish_json(topic=topic, payload=payload)


def convert_office_bytes(
    *,
    filename: str,
    content: bytes,
    backend: str,
) -> bytes:
    if backend == "stub":
        return _STUB_PDF_BYTES
    if backend != "libreoffice":
        raise PermanentError(f"Unsupported conversion backend: {backend}")

    converter = _libreoffice_bin()
    suffix = Path(filename).suffix or ".doc"
    with tempfile.TemporaryDirectory() as tmpdir:
        in_path = Path(tmpdir) / f"input{suffix}"
        in_path.write_bytes(content)
        out_dir = Path(tmpdir)
        _run_libreoffice(converter, in_path, out_dir)
        out_path = out_dir / f"{in_path.stem}.pdf"
        if not out_path.exists():
            raise PermanentError("LibreOffice did not produce PDF output")
        return out_path.read_bytes()


def _libreoffice_bin() -> str:
    override = os.getenv("LIBREOFFICE_BIN")
    if override:
        return override
    return "soffice"


def _run_libreoffice(binary: str, input_path: Path, out_dir: Path) -> None:
    cmd = [
        binary,
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        out_dir.as_posix(),
        input_path.as_posix(),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise RecoverableError(
            f"LibreOffice conversion failed (code {result.returncode}): {message}"
        )


def conversion_backend() -> str:
    env = os.getenv("ENV", "dev").lower()
    default = "stub" if env in {"dev", "local", "test"} else "libreoffice"
    return os.getenv("OFFICE_CONVERSION_BACKEND", default).strip().lower()


def conversion_mode() -> str:
    env = os.getenv("ENV", "dev").lower()
    default = "inline" if env in {"dev", "local", "test"} else "queue"
    return os.getenv("OFFICE_CONVERSION_MODE", default).strip().lower()


def max_payload_bytes() -> int:
    raw = os.getenv("OFFICE_CONVERSION_MAX_BYTES") or os.getenv("MAX_RAW_BYTES") or ""
    try:
        return int(raw)
    except ValueError:
        return 0


def validate_payload_size(content: bytes) -> None:
    limit = max_payload_bytes()
    if limit and len(content) > limit:
        raise PermanentError(f"Payload exceeds OFFICE_CONVERSION_MAX_BYTES ({limit})")


def create_job_record(
    *,
    filename: str,
    content_base64: str,
    status: str,
    output_uri: str | None = None,
    error: str | None = None,
) -> OfficeConversionJob:
    now = datetime.now(timezone.utc).isoformat()
    return OfficeConversionJob(
        id=str(uuid.uuid4()),
        filename=filename,
        content_base64=content_base64,
        status=status,
        output_uri=output_uri,
        error=error,
        created_at=now,
        updated_at=now,
    )


def update_job_record(
    job: OfficeConversionJob,
    *,
    status: str,
    output_uri: str | None = None,
    error: str | None = None,
) -> OfficeConversionJob:
    return OfficeConversionJob(
        id=job.id,
        filename=job.filename,
        content_base64=job.content_base64,
        status=status,
        output_uri=output_uri,
        error=error,
        created_at=job.created_at,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def decode_payload(content_base64: str) -> bytes:
    try:
        return base64.b64decode(content_base64, validate=True)
    except ValueError as exc:
        raise PermanentError("Invalid base64 payload") from exc
