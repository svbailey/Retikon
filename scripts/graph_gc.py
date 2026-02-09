#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

import fsspec

from retikon_core.compaction.gc import build_gc_plan, execute_gc


def _default_graph_root() -> str | None:
    bucket = os.getenv("GRAPH_BUCKET", "").strip()
    prefix = os.getenv("GRAPH_PREFIX", "").strip()
    if not bucket or not prefix:
        return None
    if bucket.startswith("gs://") or bucket.startswith("s3://"):
        return f"{bucket.rstrip('/')}/{prefix.strip('/')}"
    return f"gs://{bucket.strip('/')}/{prefix.strip('/')}"


def _write_audit_log(graph_root: str, audit_prefix: str, payload: dict) -> str:
    fs, path = fsspec.core.url_to_fs(graph_root)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    audit_prefix = audit_prefix.strip("/")
    audit_path = f"{path.rstrip('/')}/{audit_prefix}/gc-{timestamp}.json"
    with fs.open(audit_path, "w") as handle:
        json.dump(payload, handle, separators=(",", ":"))
    return f"{graph_root.rstrip('/')}/{audit_prefix}/gc-{timestamp}.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Garbage-collect GraphAr parquet not referenced by recent manifests."
    )
    parser.add_argument(
        "--graph-root",
        default=_default_graph_root(),
        help="Graph root URI, e.g. gs://bucket/prefix (defaults to GRAPH_BUCKET/GRAPH_PREFIX).",
    )
    parser.add_argument(
        "--keep-recent-hours",
        type=int,
        default=24,
        help="Keep manifests completed within the last N hours.",
    )
    parser.add_argument(
        "--keep-compaction",
        type=int,
        default=2,
        help="Keep the N most recent compaction manifests.",
    )
    parser.add_argument(
        "--keep-latest",
        type=int,
        default=1,
        help="Keep the N most recent manifests of any type.",
    )
    parser.add_argument(
        "--include-sizes",
        action="store_true",
        help="Compute total candidate bytes (slower).",
    )
    parser.add_argument(
        "--exclude-prefix",
        action="append",
        default=["audit", "snapshots"],
        help="Prefix under graph root to exclude from deletion (repeatable).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Delete candidates. By default this is a dry run.",
    )
    parser.add_argument(
        "--audit-prefix",
        default="audit/gc",
        help="Prefix under graph root to store audit logs.",
    )
    parser.add_argument(
        "--no-audit",
        action="store_true",
        help="Skip writing audit logs.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Delete batch size.",
    )

    args = parser.parse_args()
    if not args.graph_root:
        raise SystemExit("graph_root is required (set GRAPH_BUCKET/GRAPH_PREFIX or pass --graph-root).")

    plan = build_gc_plan(
        graph_root=args.graph_root,
        keep_recent_hours=args.keep_recent_hours,
        keep_compaction=args.keep_compaction,
        keep_latest=args.keep_latest,
        include_candidate_sizes=args.include_sizes,
        exclude_prefixes=args.exclude_prefix,
    )

    print(f"Graph root: {plan.graph_root}")
    print(f"Keep manifests: {len(plan.keep_manifests)}")
    print(f"Candidate parquet: {plan.total_candidates}")
    if plan.total_candidates_bytes is not None:
        print(f"Candidate bytes: {plan.total_candidates_bytes}")

    audit_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "graph_root": plan.graph_root,
        "dry_run": not args.execute,
        "keep_recent_hours": args.keep_recent_hours,
        "keep_compaction": args.keep_compaction,
        "keep_latest": args.keep_latest,
        "exclude_prefixes": list(args.exclude_prefix),
        "keep_manifests": [entry.uri for entry in plan.keep_manifests],
        "candidate_count": plan.total_candidates,
        "candidate_bytes": plan.total_candidates_bytes,
        "candidate_files": list(plan.candidate_files),
    }

    if not args.execute:
        if not args.no_audit:
            audit_uri = _write_audit_log(
                plan.graph_root, args.audit_prefix, audit_payload
            )
            print(f"Audit log: {audit_uri}")
        print("Dry run only. Use --execute to delete.")
        return 0

    deleted = execute_gc(plan=plan, dry_run=False, batch_size=args.batch_size)
    print(f"Deleted parquet files: {deleted}")
    audit_payload["deleted_count"] = deleted
    audit_payload["deleted_files"] = list(plan.candidate_files)
    if not args.no_audit:
        audit_uri = _write_audit_log(plan.graph_root, args.audit_prefix, audit_payload)
        print(f"Audit log: {audit_uri}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
