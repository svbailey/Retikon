from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class IngestSource:
    bucket: str
    name: str
    generation: str
    content_type: str | None
    size_bytes: int | None
    md5_hash: str | None
    crc32c: str | None
    local_path: str
    org_id: str | None = None
    site_id: str | None = None
    stream_id: str | None = None
    metadata: dict[str, str] | None = None
    uri_scheme: str | None = None

    @property
    def uri(self) -> str:
        if self.uri_scheme:
            scheme = self.uri_scheme.strip().lower()
            if scheme in {"file", "local"}:
                return Path(self.local_path).resolve().as_uri()
            return f"{scheme}://{self.bucket}/{self.name}"
        return f"gs://{self.bucket}/{self.name}"

    @property
    def extension(self) -> str:
        if "." not in self.name:
            return ""
        return f".{self.name.rsplit('.', 1)[-1].lower()}"
