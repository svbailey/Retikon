from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StorageEvent:
    bucket: str
    name: str
    generation: str
    content_type: str | None
    size: int | None
    md5_hash: str | None
    crc32c: str | None

    @property
    def extension(self) -> str:
        if "." not in self.name:
            return ""
        return f".{self.name.rsplit('.', 1)[-1].lower()}"
