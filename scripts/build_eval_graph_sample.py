#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import PurePosixPath
import threading
from typing import Iterable
from urllib.parse import urlparse

import gcsfs


@dataclass(frozen=True)
class GraphRoot:
    bucket: str
    prefix: str

    @property
    def uri(self) -> str:
        prefix = self.prefix.strip("/")
        if prefix:
            return f"gs://{self.bucket}/{prefix}"
        return f"gs://{self.bucket}"

    def join(self, *parts: str) -> str:
        base = PurePosixPath(self.prefix.strip("/"))
        path = base.joinpath(*[part.strip("/") for part in parts if part])
        return f"gs://{self.bucket}/{path.as_posix()}"


def _parse_graph_uri(uri: str) -> GraphRoot:
    parsed = urlparse(uri)
    if parsed.scheme != "gs" or not parsed.netloc:
        raise ValueError(f"Expected gs:// URI, got: {uri}")
    prefix = parsed.path.lstrip("/")
    return GraphRoot(bucket=parsed.netloc, prefix=prefix)


def _rel_path(root: GraphRoot, uri: str) -> str | None:
    parsed = urlparse(uri)
    if parsed.scheme != "gs" or parsed.netloc != root.bucket:
        return None
    full_path = PurePosixPath(parsed.path.lstrip("/"))
    base = PurePosixPath(root.prefix.strip("/"))
    try:
        return str(full_path.relative_to(base))
    except ValueError:
        return None


def _list_manifests(fs: gcsfs.GCSFileSystem, root: GraphRoot) -> list[str]:
    glob = f"{root.bucket}/{root.prefix.strip('/')}/manifests/*/manifest.json"
    return sorted(f"gs://{path}" for path in fs.glob(glob))


def _load_manifest(fs: gcsfs.GCSFileSystem, uri: str) -> dict:
    parsed = urlparse(uri)
    path = f"{parsed.netloc}{parsed.path}"
    with fs.open(path, "rb") as handle:
        return json.load(handle)


def _write_manifest(fs: gcsfs.GCSFileSystem, uri: str, payload: dict) -> None:
    parsed = urlparse(uri)
    path = f"{parsed.netloc}{parsed.path}"
    fs.makedirs(str(PurePosixPath(path).parent), exist_ok=True)
    with fs.open(path, "wb") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"))


_thread_local = threading.local()


def _thread_fs() -> gcsfs.GCSFileSystem:
    fs = getattr(_thread_local, "fs", None)
    if fs is None:
        fs = gcsfs.GCSFileSystem()
        _thread_local.fs = fs
    return fs


def _copy_one(src: str, dst: str) -> None:
    fs = _thread_fs()
    src_parsed = urlparse(src)
    dst_parsed = urlparse(dst)
    src_path = f"{src_parsed.netloc}{src_parsed.path}"
    dst_path = f"{dst_parsed.netloc}{dst_parsed.path}"
    if fs.exists(dst_path):
        return
    fs.makedirs(str(PurePosixPath(dst_path).parent), exist_ok=True)
    fs.copy(src_path, dst_path)


def _copy_files(
    sources: Iterable[tuple[str, str]],
    *,
    dry_run: bool,
    workers: int,
    progress_every: int,
) -> None:
    if dry_run:
        for src, dst in sources:
            print(f"[dry-run] copy {src} -> {dst}")
        return

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_copy_one, src, dst) for src, dst in sources]
        for idx, future in enumerate(as_completed(futures), start=1):
            future.result()
            if progress_every and idx % progress_every == 0:
                print(f"Copied {idx}/{len(futures)} files...")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a smaller GraphAr eval dataset.")
    parser.add_argument("--src-graph-uri", required=True)
    parser.add_argument("--dest-graph-uri", required=True)
    parser.add_argument("--manifest-count", type=int, default=200)
    parser.add_argument(
        "--pick",
        choices=("first", "latest"),
        default="latest",
        help="Pick manifests by sorted name (first N or latest N).",
    )
    parser.add_argument("--copy-workers", type=int, default=16)
    parser.add_argument(
        "--copy-progress-every",
        type=int,
        default=500,
        help="Emit progress every N copies (0 to disable).",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    fs = gcsfs.GCSFileSystem()
    src_root = _parse_graph_uri(args.src_graph_uri)
    dest_root = _parse_graph_uri(args.dest_graph_uri)

    manifests = _list_manifests(fs, src_root)
    if not manifests:
        raise SystemExit(f"No manifests found under {src_root.uri}")

    if args.pick == "latest":
        selected = manifests[-args.manifest_count :]
    else:
        selected = manifests[: args.manifest_count]

    print(f"Selected {len(selected)} manifests from {src_root.uri}")

    file_copies: list[tuple[str, str]] = []
    for manifest_uri in selected:
        payload = _load_manifest(fs, manifest_uri)
        files = payload.get("files", [])
        if not isinstance(files, list):
            files = []
        updated_files = []
        for item in files:
            if not isinstance(item, dict):
                continue
            uri = item.get("uri")
            if not uri:
                continue
            rel = _rel_path(src_root, uri)
            if rel is None:
                updated_files.append(item)
                continue
            dest_uri = dest_root.join(rel)
            file_copies.append((uri, dest_uri))
            updated_item = dict(item)
            updated_item["uri"] = dest_uri
            updated_files.append(updated_item)
        payload["files"] = updated_files
        manifest_rel = _rel_path(src_root, manifest_uri)
        if manifest_rel is None:
            raise SystemExit(f"Manifest not under source root: {manifest_uri}")
        dest_manifest_uri = dest_root.join(manifest_rel)
        if args.dry_run:
            print(f"[dry-run] write manifest {dest_manifest_uri}")
        else:
            _write_manifest(fs, dest_manifest_uri, payload)

    unique_copies = sorted(set(file_copies))
    print(f"Copying {len(unique_copies)} GraphAr files to {dest_root.uri}")
    _copy_files(
        unique_copies,
        dry_run=args.dry_run,
        workers=max(args.copy_workers, 1),
        progress_every=max(args.copy_progress_every, 0),
    )

    print("Sample graph build complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
