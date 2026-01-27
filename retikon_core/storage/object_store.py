from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlparse

import fsspec


@dataclass(frozen=True)
class ObjectStore:
    base_uri: str
    fs: fsspec.AbstractFileSystem
    base_path: str
    is_remote: bool

    @classmethod
    def from_base_uri(cls, base_uri: str) -> "ObjectStore":
        parsed = urlparse(base_uri)
        if parsed.scheme == "file":
            base_path = parsed.path
            fs = fsspec.filesystem("file")
            return cls(base_uri=base_uri, fs=fs, base_path=base_path, is_remote=False)
        if parsed.scheme and parsed.netloc:
            fs, path = fsspec.core.url_to_fs(base_uri)
            return cls(base_uri=base_uri, fs=fs, base_path=path, is_remote=True)
        fs = fsspec.filesystem("file")
        return cls(base_uri=base_uri, fs=fs, base_path=base_uri, is_remote=False)

    def join(self, *parts: str) -> str:
        safe_parts = [part.strip("/") for part in parts if part]
        if self.is_remote:
            return "/".join([self.base_path.rstrip("/"), *safe_parts])
        return str(Path(self.base_path).joinpath(*safe_parts))

    def open(self, path: str, mode: str = "rb") -> BinaryIO:
        return self.fs.open(path, mode)

    def makedirs(self, path: str) -> None:
        self.fs.makedirs(path, exist_ok=True)


def atomic_write_bytes(dest_path: str, payload: bytes) -> None:
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=str(dest.parent)) as tmp:
        tmp.write(payload)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = tmp.name
    os.replace(tmp_path, dest_path)
