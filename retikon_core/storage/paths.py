from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


def _strip_slashes(value: str) -> str:
    return value.strip("/")


def _join_parts(parts: Iterable[str]) -> str:
    return "/".join(_strip_slashes(part) for part in parts if part)


def graph_root(bucket: str, prefix: str) -> str:
    parsed = urlparse(bucket)
    if parsed.scheme:
        if parsed.scheme == "file":
            base = f"file://{parsed.path}"
        elif parsed.netloc:
            base = f"{parsed.scheme}://{parsed.netloc}"
            if parsed.path and parsed.path != "/":
                base = f"{base}/{_strip_slashes(parsed.path)}"
        else:
            base = bucket.rstrip("/")
    else:
        base = f"gs://{_strip_slashes(bucket)}"
    if not prefix:
        return base
    return f"{base}/{_strip_slashes(prefix)}"


def join_uri(base_uri: str, *parts: str) -> str:
    parsed = urlparse(base_uri)
    if parsed.scheme == "file":
        safe_parts = [_strip_slashes(part) for part in parts if part]
        return str(Path(parsed.path).joinpath(*safe_parts))
    if parsed.scheme and parsed.netloc:
        base = base_uri.rstrip("/")
        return f"{base}/{_join_parts(parts)}"
    safe_parts = [_strip_slashes(part) for part in parts if part]
    return str(Path(base_uri).joinpath(*safe_parts))


def vertex_dir(vertex_type: str, file_kind: str) -> str:
    return _join_parts(("vertices", vertex_type, file_kind))


def edge_dir(edge_type: str) -> str:
    return _join_parts(("edges", edge_type, "adj_list"))


def part_filename(part_id: str) -> str:
    return f"part-{part_id}.parquet"


def vertex_part_uri(
    base_uri: str,
    vertex_type: str,
    file_kind: str,
    part_id: str,
) -> str:
    return join_uri(
        base_uri,
        vertex_dir(vertex_type, file_kind),
        part_filename(part_id),
    )


def edge_part_uri(base_uri: str, edge_type: str, part_id: str) -> str:
    return join_uri(base_uri, edge_dir(edge_type), part_filename(part_id))


def manifest_uri(base_uri: str, run_id: str) -> str:
    return join_uri(base_uri, "manifests", run_id, "manifest.json")


@dataclass(frozen=True)
class GraphPaths:
    base_uri: str

    def vertex(self, vertex_type: str, file_kind: str, part_id: str) -> str:
        return vertex_part_uri(self.base_uri, vertex_type, file_kind, part_id)

    def edge(self, edge_type: str, part_id: str) -> str:
        return edge_part_uri(self.base_uri, edge_type, part_id)

    def manifest(self, run_id: str) -> str:
        return manifest_uri(self.base_uri, run_id)
