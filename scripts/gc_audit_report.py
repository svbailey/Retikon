#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime

import fsspec


def _default_graph_root() -> str | None:
    bucket = os.getenv("GRAPH_BUCKET", "").strip()
    prefix = os.getenv("GRAPH_PREFIX", "").strip()
    if not bucket or not prefix:
        return None
    if bucket.startswith(("gs://", "s3://")):
        return f"{bucket.rstrip('/')}/{prefix.strip('/')}"
    return f"gs://{bucket.strip('/')}/{prefix.strip('/')}"


def _list_audit_logs(graph_root: str, audit_prefix: str) -> list[str]:
    fs, path = fsspec.core.url_to_fs(graph_root)
    audit_path = f"{path.rstrip('/')}/{audit_prefix.strip('/')}"
    if not fs.exists(audit_path):
        return []
    entries = fs.glob(f"{audit_path}/gc-*.json")
    return sorted(entries)


def _load_payload(graph_root: str, path: str) -> dict:
    fs, _ = fsspec.core.url_to_fs(graph_root)
    with fs.open(path, "r") as handle:
        return json.load(handle)


def _open_output(path: str):
    fs, fs_path = fsspec.core.url_to_fs(path)
    directory = os.path.dirname(fs_path)
    if directory:
        fs.makedirs(directory, exist_ok=True)
    return fs.open(fs_path, "w")


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize GC audit logs.")
    parser.add_argument(
        "--graph-root",
        default=_default_graph_root(),
        help="Graph root URI, e.g. gs://bucket/prefix.",
    )
    parser.add_argument("--audit-prefix", default="audit/gc")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--output", help="Optional JSON output path (local or gs://)")
    args = parser.parse_args()

    if not args.graph_root:
        raise SystemExit("graph_root is required (set GRAPH_BUCKET/GRAPH_PREFIX).")

    logs = _list_audit_logs(args.graph_root, args.audit_prefix)
    if not logs:
        print("No audit logs found.")
        return 1

    selected = logs[-args.limit :]
    summaries = []
    for entry in selected:
        payload = _load_payload(args.graph_root, entry)
        summaries.append(
            {
                "audit_uri": f"{args.graph_root.rstrip('/')}/{args.audit_prefix.strip('/')}/{os.path.basename(entry)}",
                "timestamp": payload.get("timestamp"),
                "dry_run": payload.get("dry_run"),
                "candidate_count": payload.get("candidate_count"),
                "candidate_bytes": payload.get("candidate_bytes"),
                "deleted_count": payload.get("deleted_count"),
            }
        )

    payload = {"summaries": summaries}
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.output:
        with _open_output(args.output) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
